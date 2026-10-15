# mixtape

Your own music for your channel. Pick a style from a library of about 100 styles from all over the
world, say the mood, and the tool makes the music with an AI model, joins the pieces into a mixtape
with cross-fades, sets YouTube loudness, and renders a video: wide for a normal upload, vertical for
Shorts (cut into parts of at most 3 minutes, which is the Shorts limit).

Nothing is copied from anyone. The music is generated from words, so there is no copyright claim on it.

## The rules (read first)

- A "reference" song is used for its **style only**: tempo, mood, instruments, era. Name the song in
  the brief under `reference`; that line is for your notes and is never sent to the model.
- Never paste a real song's lyrics or melody, and never ask for a real singer's voice. The tool only
  sends the style words. A copy of a tune is still a copyright problem, even when a machine made it.
- Generation costs money (about 5 to 40 US cents per minute of music depending on the model).
  `plan` shows the estimate before anything is made and `run --max-usd` caps the spend of that run
  (what earlier runs spent stays in the ledger but does not count against the cap).
  `out/ledger.json` records every cent.
- Quality settings are fixed and never lowered: 48 kHz stereo, -14 LUFS (YouTube's level),
  video 1920x1080 or 1080x1920, 30 fps, libx264 crf 18, AAC 192k.

## Setup

- Python 3.10 or newer and ffmpeg on the PATH (same as docbuild).
- A fal.ai key in the `FAL_KEY` environment variable, or in `~/.mixtape/fal_key`. The docbuild
  studio's key in `~/.docbuild/fal_key` is picked up too.
- No other installs. Tests: `pip install pytest` then `python -m pytest -q`.

## A brief

`examples/monsoon-lofi.json`:

```json
{
  "title": "Monsoon Evening Lo-fi",
  "target_seconds": 300,
  "artwork": "cover*.jpg",
  "defaults": {"model": "ace-step", "variants": 2, "crossfade": 4},
  "tracks": [
    {"id": "rain-start", "style": "lofi", "mood": "rain on a Bangalore window", "seconds": 120},
    {"id": "flute-middle", "style": "bollywood-90s-romantic", "instruments": "bansuri flute over soft lo-fi drums", "seconds": 120},
    {"id": "night-end", "style": "chillhop", "mood": "late night, gentle close", "seconds": 90}
  ]
}
```

Track fields: `style` (a key from `styles`), `mood`, `instruments`, `bpm`, `prompt` (free words, can
replace the style), `seconds`, `variants` (how many takes to choose from), `model`, `lyrics` (your own
words; only the singing models accept them), `reference` (notes only).

## Commands

```
python -m mixtape styles                 # the whole library, by group
python -m mixtape styles indian flute    # search it
python -m mixtape plan brief.json        # prompts and cost, makes nothing
python -m mixtape run brief.json --max-usd 2
python -m mixtape status brief.json
python -m mixtape pick brief.json rain-start 2      # after listening to out/takes/
python -m mixtape mix brief.json         # out/mixtape.wav and out/mixtape.m4a
python -m mixtape video brief.json       # out/mixtape-wide.mp4 (add --kind shorts for vertical)
python -m mixtape shorts brief.json      # out/short-1.mp4, short-2.mp4 ... each 3 minutes or less
```

`run` can be stopped and started again: finished takes are kept and only the missing ones are made.
A track longer than a model's limit is made in pieces and joined by `mix`.

## Without fal.ai (the inbox method)

Set `"backend": "inbox"` in the brief, run `python -m mixtape jobs brief.json`, and `JOBS.md` lists every
piece with its exact prompt and file name. Make them on any music site or a free local model, save
them in the `inbox` folder under those names, then `collect`, `pick`, `mix`, `video`. Check that site's
terms allow you to use its output on YouTube.

## Models

`mixtape/models.json`. Default is `ace-step` (cheap, up to 4 minutes a piece, good for beats and
instrumentals). `lyria2` sounds best for orchestral and acoustic. `minimax-music` sings your own lyrics.
`elevenlabs-music` makes full structured tracks up to 5 minutes but costs the most. All endpoints are
marked `verified: false` until a real session confirms them with one cheap test; fix any field fal.ai
complains about in that file.

## How a Claude session uses this

Give it a style or a reference song and a length, and it writes the brief, runs `plan`, tells you the
cost and asks once, then `run`, listens to nothing (it cannot hear), so **you** pick the takes, then it
runs `mix`, `video` or `shorts`. Keep LESSONS.md notes in the brief's folder like the film projects.
