# Tales of Bob — Broken Tusk Rising

Custom RSS feeds for loading *Tales of Bob*'s "Broken Tusk Rising"
campaign onto a [Yoto Player](https://yotoplay.com/) via a custom RSS
card.

## Why this exists

- Yoto's custom RSS card only loads the **latest 25 items** from a feed
  and plays them **newest → oldest**.
- The show's real feed mixes the main Broken Tusk Rising campaign (93
  chapters, 000–092) with unrelated side content: a short "Cowboy Bebop
  RPG" side-campaign, two one-shots, and a trailer.
- **The feed's `itunes:season`/`itunes:episode` tags can't be trusted** to
  pick out just the main campaign:
  - Chapters 1–61 are tagged season 1.
  - Chapters 62–69 are tagged season 3 — not a real new season, just an
    inconsistently-tagged continuation of the same campaign.
  - Chapters 70–92 (the 23 most recent as of when this was built) have
    **no season tag at all**.
  - "Season 2" is actually the unrelated Cowboy Bebop side-campaign.
  - "Season 3, Episode 1" is a mislabeled one-shot holiday special
    (Honey Heist), not part of the Broken Tusk Rising sequence.

So instead of filtering by season, `build_feeds.py` matches episode
titles against `Broken Tusk Rising Chapter (\d+) [Pathfinder 2E]` to
build the canonical chapter order directly, ignoring the season field
entirely. 93 chapters is also well over Yoto's 25-track limit regardless.

To work around both problems, this folder publishes trimmed, reordered
feeds, split into parts that each fit under the limit:

| Feed | Chapters | File |
|---|---|---|
| Part 1 | 0–23 | [`feeds/broken-tusk-rising-part1.xml`](feeds/broken-tusk-rising-part1.xml) |
| Part 2 | 24–47 | [`feeds/broken-tusk-rising-part2.xml`](feeds/broken-tusk-rising-part2.xml) |
| Part 3 | 48–71 | [`feeds/broken-tusk-rising-part3.xml`](feeds/broken-tusk-rising-part3.xml) |
| Part 4 | 72–92 | [`feeds/broken-tusk-rising-part4.xml`](feeds/broken-tusk-rising-part4.xml) |

Each feed contains only Broken Tusk Rising chapters (no side-campaign,
one-shot, or trailer tracks) and has fake, evenly-spaced `pubDate`s
assigned in *reverse* order, so that when Yoto sorts newest-first,
playback comes out in correct chapter order (Chapter 0 of the part
first, last chapter of the part last). The actual audio files, titles,
and descriptions are untouched — pulled straight from the source feed.

## ⚠️ Ads

These feeds only reorder/filter which *chapters* play and in what order
-- they don't touch the audio itself. The source audio (served through
Megaphone) has real ads baked into it -- confirmed both directly (a
State Farm ad on one chapter) and via Megaphone's own
`x-megaphone-payload-2` response header (an exact byte-offset map of
every ad segment). A custom-RSS card built from these feeds will play
those ads unedited.

If that matters to you (e.g. this is going on a kid's player), use
[`tools/yoto-uploader/`](../../tools/yoto-uploader/) instead, with
`strip_ads: megaphone-header` set for this show (already configured in
its `podcasts.yaml` entry) -- it downloads each episode, reads that same
header, and cuts every ad segment out before uploading real MYO cards.
There's no equivalent ad-stripping for the plain RSS-feed approach.

## Use with Yoto

Add one custom RSS card per feed in the Yoto app/console, using its raw URL:

Part 1 (Chapters 0–23):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/tales-of-bob/feeds/broken-tusk-rising-part1.xml
```

Part 2 (Chapters 24–47):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/tales-of-bob/feeds/broken-tusk-rising-part2.xml
```

Part 3 (Chapters 48–71):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/tales-of-bob/feeds/broken-tusk-rising-part3.xml
```

Part 4 (Chapters 72–92):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/tales-of-bob/feeds/broken-tusk-rising-part4.xml
```

## Rebuilding the feeds

The feeds are generated from the live source feed
(`https://feeds.simplecast.com/_6JPR3jO`) by `build_feeds.py`:

```
python3 podcasts/tales-of-bob/build_feeds.py
```

Re-run it if the source feed changes (e.g. episode metadata corrections,
or new Broken Tusk Rising chapters — the chapter-count and part
boundaries are hardcoded in `PARTS`, so extend that list as new chapters
are published).

## Source

Podcast: [Tales of Bob](https://thehouseofbob.org/) by House of Bob. This
is an unofficial, personal listening aid and redistributes no audio —
feed items link to the original hosted audio files.
