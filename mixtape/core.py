"""The brief, the prompts, the plan, the generation with a money cap, the inbox, the picks."""
from __future__ import annotations

import datetime as dt
import glob
import json
import math
import os
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEGATIVE = "vocals, singing, speech, lyrics, low quality, distortion, noise, clipping, abrupt ending"
SHORTS_MAX = 180          # YouTube Shorts: 3 minutes


class BriefError(Exception):
    pass


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_styles(path=None):
    return load_json(path or HERE / "styles.json")["styles"]


def load_models(path=None):
    return load_json(path or HERE / "models.json")


def find_styles(styles, words):
    words = [w.lower() for w in words]
    out = []
    for key, s in styles.items():
        hay = " ".join([key, s["group"], s["name"], s["prompt"], s.get("like", "")]).lower()
        if all(w in hay for w in words):
            out.append((key, s))
    return out


class Brief:
    """A mixtape brief (JSON). Minimal example:
    {"title": "Monsoon Lo-fi", "target_seconds": 300, "tracks": [{"id": "t1", "style": "lofi", "seconds": 150}]}"""

    def __init__(self, path, styles=None, models=None):
        self.path = Path(path)
        self.dir = self.path.parent
        self.data = load_json(path)
        self.styles = styles or load_styles()
        self.models = models or load_models()
        self.title = self.data.get("title", self.path.stem)
        self.target = int(self.data.get("target_seconds", 300))
        self.backend = self.data.get("backend", "api")
        self.defaults = {"model": self.models.get("default", "ace-step"), "variants": 2, "seconds": 120,
                         "vocals": False, "crossfade": 3.0, "lufs": -14.0}
        self.defaults.update(self.data.get("defaults", {}))
        self.tracks = []
        ids = set()
        for i, t in enumerate(self.data.get("tracks", []), 1):
            t = dict(t)
            t.setdefault("id", f"track-{i}")
            if t["id"] in ids:
                raise BriefError(f"two tracks called {t['id']}")
            ids.add(t["id"])
            if t.get("style") and t["style"] not in self.styles:
                near = ", ".join(k for k, _ in find_styles(self.styles, t["style"].split("-")[:1])[:6])
                raise BriefError(f"track {t['id']}: unknown style '{t['style']}'. Similar: {near or 'none'}; "
                                 "run `styles` to see all")
            if not t.get("style") and not t.get("prompt"):
                raise BriefError(f"track {t['id']}: needs a style or a prompt")
            t.setdefault("seconds", self.defaults["seconds"])
            t.setdefault("variants", self.defaults["variants"])
            t.setdefault("model", self.defaults["model"])
            if t["model"] not in self.models["models"]:
                raise BriefError(f"track {t['id']}: unknown model {t['model']}")
            if t.get("lyrics") and not self.models["models"][t["model"]]["input"].get("lyrics"):
                raise BriefError(f"track {t['id']}: model {t['model']} cannot sing; use minimax-music or ace-step")
            self.tracks.append(t)
        if not self.tracks:
            raise BriefError("the brief has no tracks")
        self.out = self.dir / self.data.get("out", "out")
        self.takes = self.out / "takes"
        self.inbox = self.dir / self.data.get("inbox", "inbox")

    # ---- prompts ---------------------------------------------------------------
    def prompt(self, t):
        parts = []
        if t.get("style"):
            s = self.styles[t["style"]]
            parts.append(s["prompt"])
            if "bpm" not in t and s.get("bpm"):
                parts.append(f"around {s['bpm']} bpm")
        if t.get("bpm"):
            parts.append(f"around {t['bpm']} bpm")
        for k in ("mood", "instruments", "prompt", "extra"):
            if t.get(k):
                parts.append(t[k])
        if not t.get("lyrics") and not t.get("vocals", self.defaults["vocals"]):
            parts.append("instrumental, no vocals")
        parts.append("high quality studio recording, clear stereo mix, clean ending")
        return ", ".join(parts)

    def values(self, t, seconds):
        return {"prompt": self.prompt(t), "negative": NEGATIVE, "seconds": int(seconds),
                "milliseconds": int(seconds) * 1000, "lyrics": t.get("lyrics") or "[inst]"}

    def pieces(self, t):
        """A track longer than the model's limit is made in pieces that `mix` joins."""
        limit = self.models["models"][t["model"]]["max_seconds"]
        n = max(1, math.ceil(t["seconds"] / limit))
        return [min(limit, t["seconds"] - i * limit) for i in range(n)]

    def cost(self, t):
        m = self.models["models"][t["model"]]
        return round(m["price_per_minute"] * t["seconds"] / 60 * t["variants"], 3)

    def estimate(self):
        return round(sum(self.cost(t) for t in self.tracks), 2)

    def take_path(self, t, variant, piece=0):
        suffix = f"-p{piece + 1}" if len(self.pieces(t)) > 1 else ""
        return self.takes / f"{t['id']}__take-{variant}{suffix}.wav"

    def plan_text(self):
        total = sum(t["seconds"] for t in self.tracks)
        lines = [f"{self.title}: {len(self.tracks)} tracks, {total} s of music for a {self.target} s mixtape",
                 f"estimated cost {self.estimate():.2f} USD ({self.defaults['variants']} variants each unless set)", ""]
        if total < self.target:
            lines.append(f"WARNING: tracks add up to {total} s, less than the target {self.target} s")
        for t in self.tracks:
            m = self.models["models"][t["model"]]
            pieces = self.pieces(t)
            lines += [f"[{t['id']}] {t['seconds']} s, {t['variants']} variants, {t['model']}"
                      f"{' (' + str(len(pieces)) + ' pieces)' if len(pieces) > 1 else ''}, {self.cost(t):.2f} USD"
                      + ("" if m.get("verified") else "  (model not yet verified: test one first)"),
                      f"   reference: {t['reference']}" if t.get("reference") else "",
                      f"   prompt: {self.prompt(t)}", ""]
        return "\n".join(l for l in lines if l is not None)


# ---- ledger and picks ---------------------------------------------------------------

class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.rows = load_json(path) if self.path.exists() else []

    def spent(self):
        return round(sum(r["usd"] for r in self.rows), 3)

    def add(self, track, model, seconds, usd, file):
        self.rows.append({"at": dt.datetime.now().isoformat(timespec="seconds"), "track": track, "model": model,
                          "seconds": seconds, "usd": usd, "file": str(file)})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.rows, indent=1), encoding="utf-8")


def takes_of(brief, t):
    """Existing takes of a track, grouped by variant: {1: [p1, p2], 2: [...]}"""
    out = {}
    for p in sorted(brief.takes.glob(f"{t['id']}__take-*.*")):
        m = re.match(rf"{re.escape(t['id'])}__take-(\d+)(?:-p(\d+))?\.", p.name)
        if m:
            out.setdefault(int(m.group(1)), []).append(p)
    return out


def generate(brief, client, log, max_usd=None, only=None):
    """Make every missing take. Stops before any take that would push spending over max_usd."""
    ledger = Ledger(brief.out / "ledger.json")
    made = 0
    for t in brief.tracks:
        if only and t["id"] not in only:
            continue
        m = brief.models["models"][t["model"]]
        for v in range(1, t["variants"] + 1):
            for i, secs in enumerate(brief.pieces(t)):
                dest = brief.take_path(t, v, i)
                if dest.exists():
                    continue
                usd = round(m["price_per_minute"] * secs / 60, 3)
                if max_usd is not None and ledger.spent() + usd > max_usd:
                    log(f"cap: {ledger.spent():.2f} spent, next take {usd:.2f} would pass {max_usd:.2f} USD; stopping")
                    return made
                log(f"{dest.name}: {t['model']}, {secs} s, about {usd:.2f} USD")
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name("part-" + dest.name)
                client.generate(m, brief.values(t, secs), tmp)
                os.replace(tmp, dest)
                ledger.add(t["id"], t["model"], secs, usd, dest)
                made += 1
    log(f"{made} takes made; total spent {ledger.spent():.2f} USD")
    return made


# ---- inbox: make the music elsewhere (Suno, Udio, a free local model) and drop files here ----

def jobs_text(brief):
    lines = [f"# Jobs for {brief.title}", "",
             "Make each piece on any music site or tool, download it as MP3 or WAV, and save it in the",
             f"`{brief.inbox.name}` folder with exactly the file name shown. Then run `collect`.", "",
             "Never paste a real song's melody or lyrics; use only the words below.", ""]
    for t in brief.tracks:
        for v in range(1, t["variants"] + 1):
            for i, secs in enumerate(brief.pieces(t)):
                name = brief.take_path(t, v, i).stem
                lines += [f"## {name}", f"- length: {secs} seconds", f"- prompt: {brief.prompt(t)}"]
                if t.get("lyrics"):
                    lines.append("- lyrics: " + t["lyrics"].replace("\n", " / "))
                lines.append("")
    return "\n".join(lines)


def collect(brief, log):
    """Move files from the inbox into takes/, converting names like `t1__take-1.mp3`."""
    brief.inbox.mkdir(parents=True, exist_ok=True)
    moved = 0
    for p in sorted(brief.inbox.iterdir()):
        if p.suffix.lower() not in (".mp3", ".wav", ".m4a", ".flac", ".ogg"):
            continue
        m = re.match(r"(.+?)__take-(\d+)(?:-p(\d+))?$", p.stem)
        if not m or not any(t["id"] == m.group(1) for t in brief.tracks):
            log(f"skip {p.name}: name must be <track-id>__take-N[.-pM].mp3")
            continue
        dest = brief.takes / p.name
        brief.takes.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), dest)
        moved += 1
        log(f"collected {p.name}")
    return moved


def picks_path(brief):
    return brief.out / "picks.json"


def load_picks(brief):
    p = picks_path(brief)
    return load_json(p) if p.exists() else {}


def pick(brief, track_id, variant):
    if not any(t["id"] == track_id for t in brief.tracks):
        raise BriefError(f"no track {track_id}")
    picks = load_picks(brief)
    picks[track_id] = int(variant)
    brief.out.mkdir(parents=True, exist_ok=True)
    picks_path(brief).write_text(json.dumps(picks, indent=1), encoding="utf-8")
    return picks


def chosen_files(brief):
    """For each track in order: the files of the picked variant (or variant 1 when nothing picked)."""
    picks = load_picks(brief)
    out = []
    for t in brief.tracks:
        takes = takes_of(brief, t)
        if not takes:
            raise BriefError(f"track {t['id']} has no takes yet (run `run` or `collect`)")
        v = picks.get(t["id"], min(takes))
        if v not in takes:
            raise BriefError(f"track {t['id']}: picked take {v} does not exist; have {sorted(takes)}")
        out.append((t, takes[v]))
    return out


def status_text(brief):
    picks = load_picks(brief)
    ledger = Ledger(brief.out / "ledger.json")
    lines = [f"{brief.title}: spent {ledger.spent():.2f} USD"]
    for t in brief.tracks:
        takes = takes_of(brief, t)
        want = t["variants"] * len(brief.pieces(t))
        have = sum(len(v) for v in takes.values())
        lines.append(f"[{t['id']}] {have}/{want} files, picked: {picks.get(t['id'], '-')}")
    for name in ("mixtape.wav", "mixtape.m4a", "mixtape-wide.mp4", "mixtape-shorts.mp4"):
        if (brief.out / name).exists():
            lines.append(f"ready: {brief.out / name}")
    return "\n".join(lines)
