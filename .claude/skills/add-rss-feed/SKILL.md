---
name: add-rss-feed
description: Add a new podcast (or season/campaign) to this repo's podcasts/ custom-RSS feeds for Yoto. Use when the user gives a podcast (Apple Podcasts link, feed URL, or name) and wants it playable in order on a Yoto Player via custom RSS card, e.g. "add season 1 of X to the RSS feeds" or "how about <podcast URL>".
---

# Add a podcast to podcasts/ (custom RSS feeds)

This repo publishes trimmed, reordered RSS feeds so a Yoto custom-RSS
card plays a podcast's episodes **in correct story order**, working
around two Yoto quirks: it only loads the **latest 25 items** from a
feed, and plays them back **newest → oldest**. See existing examples
before starting: `podcasts/titans-of-allterra/`, `podcasts/sneak-attack/`
(clean `itunes:season` tagging), `podcasts/tales-of-bob/`,
`podcasts/dungeons-dragons-daughters/` (unreliable tagging, title-regex
workaround instead).

This skill is for the `podcasts/` RSS-feed side only. `tools/yoto-uploader/`
is a separate system (uploads audio directly into Yoto's MYO system) —
out of scope here unless the user explicitly asks for it too.

## Step 1: Find the real RSS feed URL

Apple Podcasts pages never list the feed URL directly. WebFetch the
Apple Podcasts page for title/author/description, and WebSearch
`"<podcast name>" podcast RSS feed` to find it (usually libsyn, simplecast,
podbean, megaphone, or similar hosting). Confirm you have the actual
`<rss>` feed, not a webpage, by fetching it.

## Step 2: Inspect the feed's real structure

Download the feed and inspect it with a script (not just eyeballing —
these feeds have surprising edge cases). Check:

1. **Total `<item>` count** and `itunes:episodeType` distribution
   (full/bonus/trailer).
2. **`itunes:season` / `itunes:episode` tag coverage**: what fraction of
   `full` items have both tags set? Any duplicates or gaps in episode
   numbers within a season?
3. **If season tagging is clean** (like Titans, Sneak Attack — every full
   episode in the target season has a matching, gapless
   `itunes:episode` sequence): you can filter by `itunes:season ==
   str(N)` directly, same as those examples.
4. **If season tagging is sparse, inconsistent, or conflates unrelated
   content** (like Tales of Bob, D&D&D — season tags missing entirely
   for recent episodes, "season 2" is actually an unrelated
   side-campaign, a bonus mislabeled into the sequence, etc.): season
   tags cannot be trusted. Look at episode **titles** instead for a
   reliable ordinal — a leading chapter/episode number, a "Chapter N",
   "Session N", or "Part N" pattern. Print titles in `pubDate` order to
   spot it. Build a regex with **one capture group** = the episode
   number, and verify it's gapless and dupe-free over the range you
   intend to publish. Untitled-pattern items (recaps, specials, promos)
   are then naturally excluded by not matching.
5. If the show clearly has **multiple seasons/campaigns and the request
   doesn't specify which**, don't guess — use AskUserQuestion to confirm
   scope before building anything (this happened for both Tales of Bob
   and D&D&D; the "obvious" choice was season 1 / the complete, wrapped
   campaign, but always confirm).
6. Sanity-check `itunes:duration`/enclosure `length` while you're in
   there if there's any chance the user also wants the MYO/playlist
   version later — not needed for the RSS feed itself, but useful
   context to mention.

## Step 3: Plan the parts

Yoto's cap is 25 items per feed. Split the target episode range into
roughly-even parts of ≤25 each: `ceil(N / 25)` parts. Prefer clean
round boundaries over exactly-even math (e.g. season1-part1 = episodes
1–23 rather than some odd remainder at the front). Look at the four
existing `podcasts/*/build_feeds.py` `PARTS`/`SEASONS` tables for the
naming/labeling convention to match.

## Step 4: Generate `podcasts/<slug>/build_feeds.py`

Copy the structure of the closest existing example (season-tag-based:
`titans-of-allterra` or `sneak-attack`; title-regex-based: `tales-of-bob`
or `dungeons-dragons-daughters`) and adapt:

- `SOURCE_FEED_URL`
- The filter function (season-tag match, or title regex + capture group)
- `PARTS` (or `SEASONS` for a multi-season show like Titans) — filename,
  human label, first/last episode number per part
- `build_channel()`'s title/link/description text
- Keep the **reverse-`pubDate`-assignment** logic unchanged: first
  episode of a part gets the newest fake date, each subsequent one an
  hour older, so Yoto's newest-first sort yields correct story order.
  This is the load-bearing trick of the whole approach — don't alter it.
- Keep namespace registration, `copy_tag` metadata copying, and XML
  writing unchanged.
- Docstring at the top should explain *why* this show needs whatever
  filtering approach you used (especially for the title-regex case —
  document the season-tag unreliability you found in Step 2, the same
  way the existing title-regex examples do, so the next person
  re-running this doesn't have to re-derive it).

Run it: `python3 podcasts/<slug>/build_feeds.py`. It should report the
episode/chapter count found and each part written, with **no
"WARNING: missing"** lines (if there are, your part boundaries don't
match reality — fix them, don't ignore the warning).

## Step 5: Verify before publishing

Don't skip this — cheap and catches real bugs:

```python
import xml.etree.ElementTree as ET
for f in ...:  # each generated feed file
    ET.parse(f)  # raises if invalid XML
```

Also spot-check one file's first/last items and their `pubDate`s to
confirm descending order (first episode = newest date).

## Step 6: Write `podcasts/<slug>/README.md`

Match the structure of existing READMEs:
- Title, one-line description
- "Why this exists" — Yoto's 25-track/newest-first quirks, plus
  whatever this show's *own* data-quality issues were (bonus tracks to
  exclude, unreliable tagging, multiple seasons/campaigns) and how you
  handled them
- Table: feed | episode range | file link
- One raw GitHub URL per part, each in its own fenced code block
  (easy to copy individually), labeled with its episode range
- "Rebuilding the feeds" section with the run command
- "Source" section crediting the original show/creator, noting this is
  an unofficial listening aid that redistributes no audio

## Step 7: Update the top-level `README.md`

Add one bullet to the `## Podcasts` list, matching the existing
one-line-per-podcast style (show name, episode count, part count,
what's excluded).

## Step 8: Commit and push

One commit covering the new `podcasts/<slug>/` directory and the
top-level README update. Commit message should state the episode
count/range and, if a title-regex workaround was needed, *why* (briefly
— the full reasoning lives in the README and script docstring).

```
git add -A
git commit -m "Add <Show> <scope> custom RSS feeds

<N> episodes (<range>), split into <M> <=25-item feeds in <story/season>
order. <One line on tagging approach/why, if non-default.>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push
```

## Step 9: Hand back the URLs

Give the user each part's raw URL in its own labeled code block (same
format as the README), so they can paste them straight into Yoto's
custom-RSS-card setup one at a time.
