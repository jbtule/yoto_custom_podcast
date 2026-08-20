# Tales from the Stinky Dragon — Campaigns 1 & 2

Custom RSS feeds for loading *Tales from the Stinky Dragon*'s first two
(complete) campaigns onto a [Yoto Player](https://yotoplay.com/) via a
custom RSS card.

## Why this exists

- Yoto's custom RSS card only loads the **latest 25 items** from a feed
  and plays them **newest → oldest**.
- The show's real feed mixes each campaign's main story episodes with
  "Between the Tales" interlude episodes (half-numbered, e.g.
  `C01 - Ep. 08.5 - ... - Between the Tales`), one-shots, and campaign
  wrap-up specials.
- **The feed's `itunes:season`/`itunes:episode` tags can't be trusted**
  to isolate just the main story:
  - `itunes:episode` numbering for Campaign 1 (tagged season 1)
    continues straight from the story finale (episode 86) into a
    3-episode post-finale bonus mini-arc ("C01 BONUS - Ep. 01–03 -
    Infinight Infirms"), numbered 87–89 as if it were more of the same
    campaign.
  - Campaign 3 ("C03") is only partially season-tagged — many of its
    later episodes have no `itunes:season` tag at all.

So instead of filtering by season, `build_feeds.py` matches episode
titles against `^C0<campaign> - Ep\. (\d+) - ` — deliberately anchored so
it does **not** match `C01 BONUS - Ep. ...` or `.5`-suffixed interlude
episodes (there's no bare `- Ep.` immediately after `C0N ` for those) —
to build each campaign's canonical episode order directly, excluding
interludes/bonus/one-shots by construction.

Campaign 3 isn't covered here — it's still ongoing, and its unreliable
tagging plus in-progress episode count means it needs a fresh look once
it wraps.

To work around the 25-track limit, this folder publishes trimmed,
reordered feeds, split into parts that each fit under it:

| Feed | Episodes | File |
|---|---|---|
| Campaign 1, Part 1 | 1–22 | [`feeds/campaign1-part1.xml`](feeds/campaign1-part1.xml) |
| Campaign 1, Part 2 | 23–44 | [`feeds/campaign1-part2.xml`](feeds/campaign1-part2.xml) |
| Campaign 1, Part 3 | 45–66 | [`feeds/campaign1-part3.xml`](feeds/campaign1-part3.xml) |
| Campaign 1, Part 4 | 67–86 | [`feeds/campaign1-part4.xml`](feeds/campaign1-part4.xml) |
| Campaign 2, Part 1 | 1–25 | [`feeds/campaign2-part1.xml`](feeds/campaign2-part1.xml) |
| Campaign 2, Part 2 | 26–50 | [`feeds/campaign2-part2.xml`](feeds/campaign2-part2.xml) |

Each feed contains only that campaign's main story episodes (no
interlude/bonus/one-shot tracks, and no other campaign) and has fake,
evenly-spaced `pubDate`s assigned in *reverse* order, so that when Yoto
sorts newest-first, playback comes out in correct episode order (Episode
1 of the part first, last episode of the part last). The actual audio
files, titles, and descriptions are untouched — pulled straight from the
source feed.

## Use with Yoto

Add one custom RSS card per feed in the Yoto app/console, using its raw URL:

Campaign 1, Part 1 (Episodes 1–22):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/stinky-dragon/feeds/campaign1-part1.xml
```

Campaign 1, Part 2 (Episodes 23–44):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/stinky-dragon/feeds/campaign1-part2.xml
```

Campaign 1, Part 3 (Episodes 45–66):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/stinky-dragon/feeds/campaign1-part3.xml
```

Campaign 1, Part 4 (Episodes 67–86):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/stinky-dragon/feeds/campaign1-part4.xml
```

Campaign 2, Part 1 (Episodes 1–25):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/stinky-dragon/feeds/campaign2-part1.xml
```

Campaign 2, Part 2 (Episodes 26–50):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/stinky-dragon/feeds/campaign2-part2.xml
```

## Rebuilding the feeds

The feeds are generated from the live source feed
(`https://feeds.megaphone.fm/stinkydragon`) by `build_feeds.py`:

```
python3 podcasts/stinky-dragon/build_feeds.py
```

Re-run it if the source feed changes (e.g. episode metadata corrections).

## Source

Podcast: [Tales from the Stinky Dragon](https://patreon.com/stinkydragon).
This is an unofficial, personal listening aid and redistributes no audio
— feed items link to the original hosted audio files.
