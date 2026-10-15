# LESSONS.md (mixtape)

Notes from sessions that used the mixtape tool, newest first. Keep the copy in your local
`mixtape-main` folder and this one in step: this file was started in the cloud on 2026-10-15
because the local LESSONS.md (items 1 to 8) was never pushed to the repository.

## 2026-10-15 — "Music" environment, Test 1 (test-2min.json): first real run attempt

Goal: set the test brief back to `"backend": "api"`, `plan`, `run --max-usd 0.50`, verify ace-step.

### What went wrong and how we solved it

- **The cloud session cannot see `D:\For Claude Usage Only\mixtape-main`.** Only the GitHub
  repository `gotanstatistics-ai/mixtape` can be attached, and it holds the code alone: no
  LESSONS.md, no CHANGELOG.md, no `Music/Test 1/test-2min.json`. The brief was written again from
  the README example (one 120 s lo-fi track, 2 variants, ace-step). If the local brief says
  something else, copy it over this one; the only field that had to change was `backend`.
  Lesson: push the `Music/` briefs and the notes files to the repository before a cloud session,
  or the session starts without them.
- **fal.ai answered 401 ("Authentication is required to access this application") to every
  request from this environment**, with and without an `Authorization` header, from the tool and
  from curl. The environment says it injects the fal.ai key for `*.fal.ai` and `*.fal.run`, but
  nothing arrived at fal.ai that it accepted. Nothing was spent. To check in the environment's
  settings (cloud environment menu, Edit, Network secrets): the fal.ai secret is present, is the
  full key (`KEY_ID:KEY_SECRET` as shown on fal.ai's Keys page) and is sent as
  `Authorization: Key <key>`. A `FAL_KEY` environment variable with the real key works too, since
  `mixtape/falapi.py` reads it. Until one of those is fixed, `run` cannot work from the cloud and
  the inbox method is the only way.
- **ace-step's input field is `tags`, not `prompt`.** fal.ai publishes every model's schema at
  `https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/ace-step` (no key, no cost).
  The required input is `tags`; `prompt` would have been ignored and the request refused. Fixed
  in `mixtape/models.json`. Also learned there: `duration` 5 to 240 s, `number_of_steps` 3 to 60
  (the file already asks for 60, the maximum, so nothing to raise), output `audio.url` as written.
  `verified` stays `false` until a real run returns a file.
- **The other models, checked the same way:** `stable-audio` (prompt, seconds_total 0 to 47, steps),
  `lyria2` (prompt, negative_prompt) and `elevenlabs/music` (prompt, music_length_ms,
  force_instrumental) match the file. `minimax-music` does not: fal.ai's version takes `prompt` as
  the lyrics and requires `reference_audio_url`, a real song with vocals to imitate. That is a
  style copy of a real recording, which README.md forbids, so the model is marked unusable in its
  notes; use ace-step with `lyrics` for singing until a lyrics-only endpoint is found.
- **A fal.ai error ends `run` with a Python traceback** instead of one line, because `cli.py`
  catches `BriefError` but not `falapi.FalError`. Harmless, but worth a two-line fix next time the
  code is open.

### What worked well

- `plan` on the recreated brief: 1 track, 120 s, 2 variants, ace-step, estimated 0.24 USD, prompt
  built from the `lofi` style plus the mood words. All 16 tests pass after the models.json change.
- Checking a model's fields from the public OpenAPI schema before spending anything. Do this for
  every new endpoint: it is the "one cheap test" from models.json made free.
