# Sneak Attack!

Custom RSS feeds for loading *Sneak Attack!*, Season 1, onto a
[Yoto Player](https://yotoplay.com/) via a custom RSS card.

## Why this exists

- Yoto's custom RSS card only loads the **latest 25 items** from a feed
  and plays them **newest → oldest**.
- The show's real feed mixes story episodes with 42 bonus tracks.
- Season 1 has **156** story episodes — way over Yoto's 25-track limit.

Unlike some other shows in this repo, Sneak Attack!'s feed tagging is
clean: Season 1's 156 full episodes are numbered 1–156 with no gaps, so
this uses the same straightforward `itunes:season`/`itunes:episode`
filtering as Titans of All'Terra, no title-pattern workaround needed.

To work around the 25-track limit, this folder publishes trimmed,
reordered feeds, split into parts that each fit under it:

| Feed | Episodes | File |
|---|---|---|
| Part 1 | 1–23 | [`feeds/season1-part1.xml`](feeds/season1-part1.xml) |
| Part 2 | 24–46 | [`feeds/season1-part2.xml`](feeds/season1-part2.xml) |
| Part 3 | 47–69 | [`feeds/season1-part3.xml`](feeds/season1-part3.xml) |
| Part 4 | 70–92 | [`feeds/season1-part4.xml`](feeds/season1-part4.xml) |
| Part 5 | 93–115 | [`feeds/season1-part5.xml`](feeds/season1-part5.xml) |
| Part 6 | 116–138 | [`feeds/season1-part6.xml`](feeds/season1-part6.xml) |
| Part 7 | 139–156 | [`feeds/season1-part7.xml`](feeds/season1-part7.xml) |

Each feed contains only "full" story episodes (no bonus tracks) and has
fake, evenly-spaced `pubDate`s assigned in *reverse* order, so that when
Yoto sorts newest-first, playback comes out in correct season order
(Episode 1 of the part first, last episode of the part last). The actual
audio files, titles, and descriptions are untouched — pulled straight
from the source feed.

## Use with Yoto

Add one custom RSS card per feed in the Yoto app/console, using its raw URL:

Part 1 (Episodes 1–23):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/sneak-attack/feeds/season1-part1.xml
```

Part 2 (Episodes 24–46):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/sneak-attack/feeds/season1-part2.xml
```

Part 3 (Episodes 47–69):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/sneak-attack/feeds/season1-part3.xml
```

Part 4 (Episodes 70–92):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/sneak-attack/feeds/season1-part4.xml
```

Part 5 (Episodes 93–115):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/sneak-attack/feeds/season1-part5.xml
```

Part 6 (Episodes 116–138):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/sneak-attack/feeds/season1-part6.xml
```

Part 7 (Episodes 139–156):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/sneak-attack/feeds/season1-part7.xml
```

## Rebuilding the feeds

The feeds are generated from the live source feed
(`https://sneakattack.libsyn.com/rss`) by `build_feeds.py`:

```
python3 podcasts/sneak-attack/build_feeds.py
```

Re-run it if the source feed changes (e.g. episode metadata corrections).

## Source

Podcast: [Sneak Attack!](https://sneakattack.libsyn.com/) by Orc Dad, LLC.
This is an unofficial, personal listening aid and redistributes no audio
— feed items link to the original hosted mp3 files.
