# CHANGELOG.md (mixtape)

## 2026-10-15 — cloud session, "Music" environment

- `mixtape/models.json`: ace-step input renamed `prompt` to `tags` (fal.ai's required field);
  notes updated with the schema limits. `minimax-music` notes warn that fal.ai's endpoint needs a
  reference song, which the tool's rules do not allow. ace-step marked `verified: true` after two
  real 120 s takes came back (0.24 USD, see the brief's ledger).
- `mixtape/core.py`: `run --max-usd` now caps the spend of the current run; earlier runs of the
  same brief stay in the ledger but no longer block new takes. README sentence updated.
- `Music/Test 1/test-2min.json`: second brief, track `bansuri` (style `ilaiyaraaja`, 75 bpm, bansuri
  lead, soft tabla and brushed drums, nostalgic 1990s South Indian film feel, intro/build/fade),
  3 variants. Earlier: the 2-minute test brief, `"backend": "api"`, one 120 s lo-fi
  track, 2 variants (recreated in the cloud; replace with the local copy if it differs).
- `Music/Green Mile Feel/green-mile-feel.json`: brief "Quiet Miracle", one 120 s track in the feel of
  Thomas Newman's Green Mile theme (style words only: slow piano melody, warm strings, oboe,
  celesta, 60 bpm, intro/swell/fade), 3 ace-step variants, 0.36 USD.
- LESSONS.md and CHANGELOG.md started in the repository (the local copies were never pushed).
- Quality settings untouched: 48 kHz stereo, -14 LUFS, 1920x1080 / 1080x1920, 30 fps, crf 18,
  AAC 192k; ace-step steps stay at the maximum 60.

## 1.0 — first version

- Style library, brief, plan with cost estimate, run with a money cap and ledger, inbox method,
  picks, mix with cross-fades and YouTube loudness, wide and Shorts video.
