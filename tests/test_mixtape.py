import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from mixtape.core import Brief, BriefError, load_styles, find_styles, generate, jobs_text, collect, pick, Ledger, status_text, takes_of
from mixtape import render, cli, falapi

log = lambda *a: None
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def write_brief(tmp_path, **over):
    data = {"title": "Test Tape", "target_seconds": 20, "defaults": {"model": "ace-step", "variants": 2, "crossfade": 1},
            "tracks": [{"id": "a", "style": "lofi", "seconds": 8}, {"id": "b", "style": "chillhop", "seconds": 8, "variants": 1}]}
    data.update(over)
    p = tmp_path / "brief.json"
    p.write_text(json.dumps(data))
    return p


def tone(path, seconds, freq=440):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={seconds}", "-ac", "2", "-ar", "48000", str(path)], check=True)


class FakeClient:
    def __init__(self):
        self.calls = []

    def generate(self, model, values, dest):
        self.calls.append((model["endpoint"], values))
        if HAVE_FFMPEG:
            tone(dest, values["seconds"])
        else:
            Path(dest).write_bytes(b"RIFF")
        return {}


# ---- styles and brief ----------------------------------------------------------------

def test_styles_library():
    styles = load_styles()
    assert len(styles) >= 90
    assert all({"group", "name", "prompt", "bpm"} <= set(s) for s in styles.values())
    assert any(k for k, _ in find_styles(styles, ["carnatic"]))
    assert "rahman-90s" in [k for k, _ in find_styles(styles, ["rahman"])]
    assert find_styles(styles, ["nothing-like-this"]) == []


def test_brief_prompt_and_cost(tmp_path):
    b = Brief(write_brief(tmp_path))
    t = b.tracks[0]
    p = b.prompt(t)
    assert "lo-fi hip hop" in p and "around 80 bpm" in p and "instrumental, no vocals" in p and p.endswith("clean ending")
    assert b.cost(t) == round(0.06 * 8 / 60 * 2, 3)
    assert b.estimate() == round(b.cost(b.tracks[0]) + b.cost(b.tracks[1]), 2)
    assert b.pieces(t) == [8]
    text = b.plan_text()
    assert "Test Tape" in text and "[a]" in text and "not yet verified" in text and "WARNING" in text  # 16 s < 20 s target


def test_brief_pieces_for_long_tracks(tmp_path):
    b = Brief(write_brief(tmp_path, tracks=[{"id": "long", "style": "ambient", "seconds": 100, "model": "stable-audio"}]))
    assert b.pieces(b.tracks[0]) == [47, 47, 6]
    assert b.take_path(b.tracks[0], 1, 2).name == "long__take-1-p3.wav"


def test_brief_errors(tmp_path):
    with pytest.raises(BriefError, match="unknown style"):
        Brief(write_brief(tmp_path, tracks=[{"id": "x", "style": "lo-fi"}]))
    with pytest.raises(BriefError, match="needs a style or a prompt"):
        Brief(write_brief(tmp_path, tracks=[{"id": "x"}]))
    with pytest.raises(BriefError, match="cannot sing"):
        Brief(write_brief(tmp_path, tracks=[{"id": "x", "style": "pop-modern", "model": "lyria2", "lyrics": "la la"}]))
    with pytest.raises(BriefError, match="two tracks"):
        Brief(write_brief(tmp_path, tracks=[{"id": "x", "style": "lofi"}, {"id": "x", "style": "lofi"}]))


def test_prompt_only_track_with_lyrics(tmp_path):
    b = Brief(write_brief(tmp_path, tracks=[{"id": "song", "prompt": "a sunny Kannada pop song", "model": "minimax-music",
                                            "lyrics": "ondu dina\nnavu hodevu"}]))
    v = b.values(b.tracks[0], 30)
    assert v["lyrics"].startswith("ondu dina") and "no vocals" not in v["prompt"] and v["milliseconds"] == 30000


# ---- generation, cap, ledger, inbox, picks ------------------------------------------

def test_generate_respects_cap_and_resumes(tmp_path):
    b = Brief(write_brief(tmp_path))
    c = FakeClient()
    made = generate(b, c, log, max_usd=0.02)          # each 8 s take = 0.008 USD -> 2 takes fit
    assert made == 2 and Ledger(b.out / "ledger.json").spent() == 0.016
    assert sorted(p.name for p in b.takes.iterdir()) == ["a__take-1.wav", "a__take-2.wav"]
    made = generate(b, c, log, max_usd=None)
    assert made == 1 and len(c.calls) == 3                 # only the missing take
    assert c.calls[0][0] == "fal-ai/ace-step" and c.calls[0][1]["lyrics"] == "[inst]"
    assert "spent 0.02 USD" in status_text(b)
    assert generate(b, c, log) == 0


def test_generate_only(tmp_path):
    b = Brief(write_brief(tmp_path))
    c = FakeClient()
    assert generate(b, c, log, only={"b"}) == 1
    assert takes_of(b, b.tracks[1]) == {1: [b.takes / "b__take-1.wav"]}


def test_jobs_and_collect(tmp_path):
    b = Brief(write_brief(tmp_path))
    text = jobs_text(b)
    assert "## a__take-1" in text and "## a__take-2" in text and "## b__take-1" in text and "## b__take-2" not in text
    b.inbox.mkdir()
    (b.inbox / "a__take-1.mp3").write_bytes(b"x")
    (b.inbox / "wrong-name.mp3").write_bytes(b"x")
    (b.inbox / "zzz__take-1.mp3").write_bytes(b"x")
    assert collect(b, log) == 1
    assert (b.takes / "a__take-1.mp3").exists() and (b.inbox / "wrong-name.mp3").exists()


def test_pick(tmp_path):
    b = Brief(write_brief(tmp_path))
    assert pick(b, "a", 2) == {"a": 2}
    with pytest.raises(BriefError):
        pick(b, "nope", 1)


# ---- render: command builders -------------------------------------------------------

def test_join_filter():
    f, total = render.join_filter(3, [10, 10, 10], 3)
    assert f.count("acrossfade") == 2 and "[out]" in f and total == 24
    f, total = render.join_filter(2, [2, 10], 3)
    assert "d=1.00" in f                                   # crossfade limited to half the shortest side
    assert render.join_filter(1, [5], 3) == ("[0:a]anull[out]", 5)


def test_video_cmd_quality_is_fixed():
    cmd = render.video_cmd("a.wav", "o.mp4", "My Tape", render.SHORTS, subtitle="part 1")
    s = " ".join(cmd)
    assert "libx264" in s and "-crf 18" in s and "1080x1920" in s and "-b:a 192k" in s and "-r 30" in s
    assert "showwaves" in s and "My Tape" in s and "part 1" in s
    cmd = render.video_cmd("a.wav", "o.mp4", "T: it's 100%", render.WIDE, artwork="c.jpg")
    s = " ".join(cmd)
    assert "gblur" in s and "scale=1920:1080" in s and "T\\: it\\'s 100\\%" in s


def test_shorts_parts():
    assert render.shorts_parts(300) == [(0, 150.0), (150.0, 300)]
    assert render.shorts_parts(170) == [(0, 170)]
    assert len(render.shorts_parts(400)) == 3


# ---- render: the real thing on tones ------------------------------------------------

@pytest.mark.skipif(not HAVE_FFMPEG, reason="needs ffmpeg")
def test_mix_video_shorts_end_to_end(tmp_path):
    b = Brief(write_brief(tmp_path, target_seconds=12, tracks=[
        {"id": "a", "style": "lofi", "seconds": 8, "variants": 1},
        {"id": "b", "style": "ambient", "seconds": 10, "variants": 1, "model": "stable-audio"}]))
    b.takes.mkdir(parents=True)
    tone(b.takes / "a__take-1.wav", 8, 440)
    tone(b.takes / "b__take-1.wav", 10, 660)
    length = render.mix(b, log)
    assert length == 12
    wav = b.out / "mixtape.wav"
    assert abs(render.duration(wav) - 12) < 0.2 and (b.out / "mixtape.m4a").exists()
    loud = render.measure_loudness(wav)
    assert abs(float(loud["input_i"]) + 14) < 1.0 and float(loud["input_tp"]) <= -0.5
    out = render.video(b, log, "wide")
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height,codec_name",
                            "-of", "json", str(out)], capture_output=True, text=True)
    st = json.loads(probe.stdout)["streams"][0]
    assert (st["width"], st["height"], st["codec_name"]) == (1920, 1080, "h264")
    outs = render.shorts(b, log)
    assert len(outs) == 1 and outs[0].exists()


@pytest.mark.skipif(not HAVE_FFMPEG, reason="needs ffmpeg")
def test_mix_joins_pieces_of_a_long_track(tmp_path):
    b = Brief(write_brief(tmp_path, target_seconds=0, tracks=[{"id": "x", "style": "ambient", "seconds": 60, "variants": 1, "model": "stable-audio"}]))
    b.takes.mkdir(parents=True)
    tone(b.takes / "x__take-1-p1.wav", 5)
    tone(b.takes / "x__take-1-p2.wav", 5)
    render.mix(b, log)
    assert abs(render.duration(b.out / "mixtape.wav") - 9) < 0.3     # 5 + 5 - 1 s crossfade


# ---- cli and fal --------------------------------------------------------------------

def test_cli(tmp_path, capsys, monkeypatch):
    p = write_brief(tmp_path)
    assert cli.main(["styles", "lofi"]) == 0 and "lofi" in capsys.readouterr().out
    assert cli.main(["plan", str(p)]) == 0 and "estimated cost" in capsys.readouterr().out
    assert cli.main(["jobs", str(p)]) == 0 and (tmp_path / "JOBS.md").exists()
    assert cli.main(["status", str(p)]) == 0
    assert cli.main(["pick", str(p), "a", "1"]) == 0
    assert cli.main(["mix", str(p)]) == 2                    # no takes yet -> BriefError
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(falapi, "load_key", lambda: None)
    assert cli.main(["run", str(p)]) == 1
    monkeypatch.setattr(falapi, "load_key", lambda: "k")
    monkeypatch.setattr(falapi, "Client", lambda http, log: FakeClient())
    assert cli.main(["run", str(p), "--max-usd", "1"]) == 0
    out = capsys.readouterr().out
    assert "[a] 2/2 files" in out and "[b] 1/1 files" in out


def test_fal_fill_and_pick():
    body = falapi.fill({"prompt": "{prompt}", "duration": "{seconds}", "lyrics": "[inst]"}, {"prompt": "x", "seconds": 30})
    assert body == {"prompt": "x", "duration": 30, "lyrics": "[inst]"}
    assert falapi.pick({"audio": {"url": "u"}}, "audio.url") == "u"
    assert falapi.pick({"images": [{"url": "u"}]}, "images[0].url") == "u"
