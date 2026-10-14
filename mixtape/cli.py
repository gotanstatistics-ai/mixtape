"""python -m mixtape <command> brief.json [options]

  styles [words]      list the style library (optionally only styles matching the words)
  plan                prompts, pieces and the estimated cost; nothing is made
  run [--max-usd N] [--only t1,t2]   make the takes through fal.ai, stopping at the cap
  jobs                write JOBS.md for the inbox method (make the music elsewhere)
  collect             move files from inbox/ into out/takes/
  status              what exists, what was picked, what was spent
  pick <track> <n>    choose take n of a track
  mix                 join the picked takes into out/mixtape.wav and .m4a at YouTube loudness
  video [--kind wide|shorts]   render one video of the whole mixtape
  shorts              cut the mixtape into Shorts of at most 3 minutes, each a vertical video
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .core import Brief, BriefError, load_styles, find_styles, generate, jobs_text, collect, pick, status_text
from . import render


def cmd_styles(args, log):
    styles = load_styles()
    hits = find_styles(styles, args.words) if args.words else list(styles.items())
    group = None
    for key, s in sorted(hits, key=lambda kv: (kv[1]["group"], kv[0])):
        if s["group"] != group:
            group = s["group"]
            print(f"\n{group}")
        print(f"  {key:<24} {s['name']:<28} ~{s['bpm']} bpm   like: {s.get('like', '')}")
    print(f"\n{len(hits)} styles")
    return 0


def cmd_plan(args, log):
    print(Brief(args.brief).plan_text())
    return 0


def cmd_run(args, log):
    brief = Brief(args.brief)
    if brief.backend == "inbox":
        log("this brief uses the inbox backend; run `jobs`, make the music, then `collect`")
        return 1
    from . import falapi
    key = falapi.load_key()
    if not key:
        log(f"no fal.ai key: set FAL_KEY or write it to {falapi.key_path()}")
        return 1
    client = falapi.Client(falapi.Http(key), log=log)
    log(f"estimated {brief.estimate():.2f} USD for everything; cap {args.max_usd if args.max_usd is not None else 'none'}")
    only = set(args.only.split(",")) if args.only else None
    generate(brief, client, log, max_usd=args.max_usd, only=only)
    print(status_text(brief))
    return 0


def cmd_jobs(args, log):
    brief = Brief(args.brief)
    brief.inbox.mkdir(parents=True, exist_ok=True)
    path = brief.dir / "JOBS.md"
    path.write_text(jobs_text(brief), encoding="utf-8")
    log(f"wrote {path}; put the finished files in {brief.inbox}")
    return 0


def cmd_collect(args, log):
    n = collect(Brief(args.brief), log)
    log(f"{n} files collected")
    return 0


def cmd_status(args, log):
    print(status_text(Brief(args.brief)))
    return 0


def cmd_pick(args, log):
    picks = pick(Brief(args.brief), args.track, args.n)
    log("picks: " + ", ".join(f"{k}={v}" for k, v in picks.items()))
    return 0


def cmd_mix(args, log):
    render.mix(Brief(args.brief), log)
    return 0


def cmd_video(args, log):
    render.video(Brief(args.brief), log, args.kind)
    return 0


def cmd_shorts(args, log):
    render.shorts(Brief(args.brief), log)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="mixtape", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("styles"); s.add_argument("words", nargs="*"); s.set_defaults(fn=cmd_styles)
    for name, fn in (("plan", cmd_plan), ("run", cmd_run), ("jobs", cmd_jobs), ("collect", cmd_collect),
                     ("status", cmd_status), ("pick", cmd_pick), ("mix", cmd_mix), ("video", cmd_video), ("shorts", cmd_shorts)):
        s = sub.add_parser(name)
        s.add_argument("brief")
        s.set_defaults(fn=fn)
        if name == "run":
            s.add_argument("--max-usd", type=float, default=None)
            s.add_argument("--only", default="")
        if name == "pick":
            s.add_argument("track"); s.add_argument("n", type=int)
        if name == "video":
            s.add_argument("--kind", choices=["wide", "shorts"], default="wide")
    args = p.parse_args(argv)
    log = lambda *a: print(*a, file=sys.stderr, flush=True)
    try:
        return args.fn(args, log)
    except BriefError as e:
        log("error: " + str(e))
        return 2
    except KeyboardInterrupt:
        log("stopped")
        return 130


