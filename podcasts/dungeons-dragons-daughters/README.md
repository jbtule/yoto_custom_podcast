# Dungeons & Dragons & Daughters — Campaign 1

Custom RSS feeds for loading *Dungeons & Dragons & Daughters*' first
campaign (chapters 0–69, now complete) onto a
[Yoto Player](https://yotoplay.com/) via a custom RSS card.

## Why this exists

- Yoto's custom RSS card only loads the **latest 25 items** from a feed
  and plays them **newest → oldest**.
- The show's real feed has almost no usable `itunes:season` tagging (108
  of 110 items are untagged — only 2 stray items carry a season tag, not
  enough to filter by).
- What the feed *does* have reliably is a leading sequential number in
  each story episode's title (`N. DDD <arc name>`). Titles without that
  leading number ("DDD Out of the Dungeon" recaps, specials, a
  cross-promo) are bonus/side content.
- That numbered sequence spans **two distinct campaigns**: chapters
  0–69 form the complete first campaign, ending at "69. DDD Our First
  Campaign Wrap!"; chapters 70+ are a second, still-ongoing campaign
  ("The Wild Beyond the Witchlight") not covered here.

So instead of filtering by season, `build_feeds.py` matches episode
titles against `^(\d+)\. DDD .+$` to build the canonical chapter order
directly, then restricts to chapters 0–69 for Campaign 1.

To work around the 25-track limit, this folder publishes trimmed,
reordered feeds, split into parts that each fit under it:

| Feed | Chapters | File |
|---|---|---|
| Part 1 | 0–23 | [`feeds/campaign1-part1.xml`](feeds/campaign1-part1.xml) |
| Part 2 | 24–46 | [`feeds/campaign1-part2.xml`](feeds/campaign1-part2.xml) |
| Part 3 | 47–69 | [`feeds/campaign1-part3.xml`](feeds/campaign1-part3.xml) |

Each feed contains only Campaign 1 story episodes (no bonus/recap/promo
tracks, and no Campaign 2) and has fake, evenly-spaced `pubDate`s
assigned in *reverse* order, so that when Yoto sorts newest-first,
playback comes out in correct chapter order (Chapter 0 of the part
first, last chapter of the part last). The actual audio files, titles,
and descriptions are untouched — pulled straight from the source feed.

## Use with Yoto

Add one custom RSS card per feed in the Yoto app/console, using its raw URL:

Part 1 (Chapters 0–23):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/dungeons-dragons-daughters/feeds/campaign1-part1.xml
```

Part 2 (Chapters 24–46):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/dungeons-dragons-daughters/feeds/campaign1-part2.xml
```

Part 3 (Chapters 47–69):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/dungeons-dragons-daughters/feeds/campaign1-part3.xml
```

## Rebuilding the feeds

The feeds are generated from the live source feed
(`https://feed.podbean.com/dungeonsdragonsdaughters/feed.xml`) by
`build_feeds.py`:

```
python3 podcasts/dungeons-dragons-daughters/build_feeds.py
```

Re-run it if the source feed changes (e.g. episode metadata corrections).
Campaign 2 ("The Wild Beyond the Witchlight," chapter 70 onward) isn't
covered here since it's still ongoing — a similar script could be added
for it later once it wraps.

## Source

Podcast: [Dungeons & Dragons & Daughters](https://dungeonsdragonsdaughters.podbean.com/),
Block Party Podcast Network. This is an unofficial, personal listening
aid and redistributes no audio — feed items link to the original hosted
audio files.
