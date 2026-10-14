"""ffmpeg: join the pieces, join the tracks with cross-fades, set YouTube loudness, make the video."""
from __future__ import annotations

import json
import math
import os
import re
import shlex
import subprocess
from pathlib import Path

from .core import SHORTS_MAX, BriefError, chosen_files

# Never lower these (same rule as docbuild).
WIDE = (1920, 1080)
SHORTS = (1080, 1920)
FPS = 30
CRF = 18
AAC = "192k"
AAC_AUDIO_ONLY = "256k"


def run(cmd, log=None, check=True):
    if log:
        log("$ " + " ".join(shlex.quote(c) for c in cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode:
        raise BriefError(f"ffmpeg failed: {r.stderr[-800:]}")
    return r


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(r.stdout)["format"]["duration"])


def join_filter(n, durations, crossfade):
    """acrossfade chain for n inputs -> (filter_complex, total length)."""
    if n == 1:
        return "[0:a]anull[out]", durations[0]
    parts, prev, total = [], "[0:a]", durations[0]
    for i in range(1, n):
        cf = max(0.1, min(crossfade, durations[i - 1] / 2, durations[i] / 2))
        out = "[out]" if i == n - 1 else f"[x{i}]"
        parts.append(f"{prev}[{i}:a]acrossfade=d={cf:.2f}:c1=tri:c2=tri{out}")
        prev = out
        total += durations[i] - cf
    return ";".join(parts), total


def join_cmd(files, out, crossfade, durations):
    f, total = join_filter(len(files), durations, crossfade)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in files:
        cmd += ["-i", str(p)]
    cmd += ["-filter_complex", f, "-map", "[out]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out)]
    return cmd, total


def measure_loudness(path):
    r = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
             "-f", "null", "-"], check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        raise BriefError("could not measure loudness: " + r.stderr[-400:])
    return json.loads(m.group(0))


def cut_cmd(src, out, length, fade_out=4.0):
    """Trim to the target length with a gentle fade at the end (done before measuring loudness)."""
    fade = min(fade_out, length / 2)
    af = f"atrim=0:{length:.2f},afade=t=out:st={max(0.0, length - fade):.2f}:d={fade:.2f}"
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", af,
            "-c:a", "pcm_s16le", str(out)]


def loudness_cmd(src, out, lufs, measured):
    """Second loudnorm pass: linear (a plain gain change, so the music is untouched) and exact."""
    lra = max(11.0, float(measured["input_lra"]) + 0.1)
    af = (f"loudnorm=I={lufs}:TP=-1:LRA={lra:.1f}:measured_I={measured['input_i']}:"
          f"measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}:"
          f"measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}:linear=true")
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", af,
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out)]


def mix(brief, log, target=None):
    """takes -> out/mixtape.wav and out/mixtape.m4a. Returns the final length in seconds."""
    chosen = chosen_files(brief)
    brief.out.mkdir(parents=True, exist_ok=True)
    cf = float(brief.defaults["crossfade"])
    track_files = []
    for t, pieces in chosen:
        if len(pieces) == 1:
            track_files.append(pieces[0])
            continue
        joined = brief.out / f"{t['id']}-joined.wav"
        cmd, _ = join_cmd(pieces, joined, min(cf, 1.5), [duration(p) for p in pieces])
        run(cmd, log)
        track_files.append(joined)
    rough = brief.out / "mixtape-rough.wav"
    cmd, total = join_cmd(track_files, rough, cf, [duration(p) for p in track_files])
    run(cmd, log)
    target = target or brief.target
    length = min(total, target) if target else total
    if total < target:
        log(f"note: the music is {total:.0f} s, shorter than the target {target} s; add a track or lengthen one")
    cut = brief.out / "mixtape-cut.wav"
    run(cut_cmd(rough, cut, length), log)
    measured = measure_loudness(cut)
    wav = brief.out / "mixtape.wav"
    run(loudness_cmd(cut, wav, float(brief.defaults["lufs"]), measured), log)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", "-b:a", AAC_AUDIO_ONLY,
         str(brief.out / "mixtape.m4a")], log)
    final = measure_loudness(wav)
    log(f"mixtape: {length:.0f} s, {float(final['input_i']):.1f} LUFS, true peak {float(final['input_tp']):.1f} dB")
    return length


def _esc(text):
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def video_cmd(audio, out, title, size, artwork=None, subtitle="", colour="0x101418", font=None):
    """Background (artwork scaled and blurred, or a flat colour), a waveform, the title. Exact quality settings."""
    w, h = size
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if artwork:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-i", str(artwork)]
        bg = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"gblur=sigma=12,eq=brightness=-0.15[bg];")
        cmd += ["-i", str(audio)]
        aud = "1:a"
    else:
        cmd += ["-f", "lavfi", "-i", f"color=c={colour}:s={w}x{h}:r={FPS}", "-i", str(audio)]
        bg = "[0:v]null[bg];"
        aud = "1:a"
    wave_h = h // 5
    fontfile = f"fontfile={font}:" if font else ""
    big = h // 18 if h > w else h // 14
    small = big * 2 // 3
    f = (bg + f"[{aud}]showwaves=s={w}x{wave_h}:mode=cline:colors=white@0.85:r={FPS}[wv];"
         f"[bg][wv]overlay=0:{h - wave_h - h // 10}[v1];"
         f"[v1]drawtext={fontfile}text='{_esc(title)}':fontcolor=white:fontsize={big}:x=(w-text_w)/2:y=h/2-text_h"
         f":shadowcolor=black@0.6:shadowx=2:shadowy=2[v2];"
         f"[v2]drawtext={fontfile}text='{_esc(subtitle)}':fontcolor=white@0.8:fontsize={small}:x=(w-text_w)/2:y=h/2+{small}"
         f":shadowcolor=black@0.6:shadowx=2:shadowy=2[v]")
    cmd += ["-filter_complex", f, "-map", "[v]", "-map", aud, "-shortest",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(CRF), "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", AAC, "-movflags", "+faststart", str(out)]
    return cmd


def artwork_of(brief):
    art = brief.data.get("artwork")
    if not art:
        return None
    hits = sorted(brief.dir.glob(art))
    if not hits:
        raise BriefError(f"artwork {art} not found in {brief.dir}")
    return hits[0]


def video(brief, log, kind="wide"):
    wav = brief.out / "mixtape.wav"
    if not wav.exists():
        raise BriefError("no mixtape.wav yet; run `mix` first")
    size = WIDE if kind == "wide" else SHORTS
    out = brief.out / f"mixtape-{kind}.mp4"
    run(video_cmd(wav, out, brief.title, size, artwork_of(brief), brief.data.get("subtitle", ""),
                  font=brief.data.get("font")), log)
    log(f"video: {out}")
    return out


def shorts_parts(length, max_len=SHORTS_MAX, overlap=0.0):
    """Split a length into equal parts no longer than max_len: 300 s -> [(0,150),(150,300)]."""
    n = max(1, math.ceil(length / max_len))
    step = length / n
    return [(round(i * step, 2), round(min(length, (i + 1) * step), 2)) for i in range(n)]


def shorts(brief, log):
    wav = brief.out / "mixtape.wav"
    if not wav.exists():
        raise BriefError("no mixtape.wav yet; run `mix` first")
    length = duration(wav)
    parts = shorts_parts(length)
    outs = []
    for i, (a, b) in enumerate(parts, 1):
        piece = brief.out / f"short-{i}.wav"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav), "-af",
             f"atrim={a}:{b},asetpts=PTS-STARTPTS,afade=t=in:d=1,afade=t=out:st={b - a - 2:.2f}:d=2",
             "-c:a", "pcm_s16le", str(piece)], log)
        out = brief.out / f"short-{i}.mp4"
        sub = f"part {i} of {len(parts)}" if len(parts) > 1 else brief.data.get("subtitle", "")
        run(video_cmd(piece, out, brief.title, SHORTS, artwork_of(brief), sub, font=brief.data.get("font")), log)
        outs.append(out)
        log(f"short {i}: {b - a:.0f} s -> {out}")
    return outs
