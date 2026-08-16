# yoto-uploader

Alternative to the `podcasts/` custom-RSS approach: instead of pointing a
Yoto custom RSS card at a feed on GitHub, this uploads audio directly into
Yoto's own "Make Your Own" (MYO) system via the [Yoto API](https://yoto.dev/),
creating real cards in your library. **No audio or tokens are ever
committed to git** — everything downloaded/uploaded lives in `.state/`,
which is gitignored.

Currently builds: **The Titans of All'Terra, Season 1** (36 episodes).

## Why this exists / how it differs from the RSS approach

The custom-RSS card in `podcasts/titans-of-allterra/` works around Yoto's
25-track feed limit. MYO cards have different limits instead:

- **1 hour max per track** — 15 of the 36 Season 1 episodes run over an
  hour, so this tool splits those into two tracks each, cut near a quiet
  moment closest to the midpoint (via `ffmpeg` silence detection), not a
  hard time cut.
- **6 hours / 500MB max per card** — episodes are greedily packed in season
  order into as few cards as those caps allow. For Season 1 today that's
  **7 cards** (an even 6-episodes-per-card split doesn't fit — two of those
  groups run over 6 hours).

Card boundaries are recomputed from the live feed each run, so the exact
card count/grouping can shift if episode lengths in the source feed ever
change.

## Setup

1. **ffmpeg**: `brew install ffmpeg` (needs `ffmpeg` and `ffprobe` on PATH).
2. **Python deps**: `pip install -r requirements.txt`
3. **Yoto developer app**: register a free public app at
   [dashboard.yoto.dev](https://dashboard.yoto.dev/) with redirect URI:
   ```
   http://127.0.0.1:8787/callback
   ```
   Copy its client ID, then:
   ```
   export YOTO_CLIENT_ID=<your client id>
   ```

## Usage

```
# Show the card plan (episode groupings, sizes) without downloading/uploading anything
python3 build_titans_season1.py --dry-run

# Do it for real -- opens a browser once to log into Yoto, then downloads,
# splits oversized episodes, uploads, and creates each card
python3 build_titans_season1.py

# Safe to re-run any time -- already-uploaded tracks and already-created
# cards are skipped via .state/titans-season1-manifest.json
python3 build_titans_season1.py --resume

# Only (re)do one card, e.g. after fixing something
python3 build_titans_season1.py --only-card 3
```

Cards appear under **My Cards** in the Yoto app once created; you still
need to link a physical MYO card icon to each one in the app to play it on
a Yoto Player.

## State

`.state/` (gitignored) holds:
- `work/titans-season1/` — downloaded and split mp3s
- `titans-season1-manifest.json` — which tracks are uploaded and which
  cards are created, so re-running the script doesn't redo work
- `credentials.json` — your cached Yoto login token
