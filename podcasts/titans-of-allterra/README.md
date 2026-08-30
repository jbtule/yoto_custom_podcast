# The Titans of All'Terra

Custom RSS feeds for loading *The Titans of All'Terra* onto a
[Yoto Player](https://yotoplay.com/) via a custom RSS card.

## Why this exists

- Yoto's custom RSS card only loads the **latest 25 items** from a feed and
  plays them **newest → oldest**.
- The show's real feed mixes story episodes with bonus tracks (cast intros,
  "autopsy" recap episodes, Kickstarter plugs, etc).
- Season 1 has **36** story episodes and Season 2 has **26** — both over
  Yoto's 25-track limit. Season 3 is ongoing and currently has **10**
  episodes (fits in a single feed for now; re-run the script and add a
  Part 2 once it passes 25).

To work around this, this folder publishes trimmed, reordered feeds, split
per season into parts that each fit under the limit:

| Feed | Episodes | File |
|---|---|---|
| Season 1, Part 1 | 1–18 | [`feeds/season1-part1.xml`](feeds/season1-part1.xml) |
| Season 1, Part 2 | 19–36 | [`feeds/season1-part2.xml`](feeds/season1-part2.xml) |
| Season 2, Part 1 | 1–13 | [`feeds/season2-part1.xml`](feeds/season2-part1.xml) |
| Season 2, Part 2 | 14–26 | [`feeds/season2-part2.xml`](feeds/season2-part2.xml) |
| Season 3, Part 1 | 1–10 | [`feeds/season3-part1.xml`](feeds/season3-part1.xml) |

Each feed contains only "full" story episodes (no bonus/trailer tracks) and
has fake, evenly-spaced `pubDate`s assigned in *reverse* order, so that when
Yoto sorts newest-first, playback comes out in correct season order
(Episode 1 of the part first, last episode of the part last). The actual
audio files, titles, and descriptions are untouched — pulled straight from
the source feed.

## Use with Yoto

Add one custom RSS card per feed in the Yoto app/console, using its raw URL:

Season 1, Part 1 (Episodes 1–18):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/titans-of-allterra/feeds/season1-part1.xml
```

Season 1, Part 2 (Episodes 19–36):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/titans-of-allterra/feeds/season1-part2.xml
```

Season 2, Part 1 (Episodes 1–13):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/titans-of-allterra/feeds/season2-part1.xml
```

Season 2, Part 2 (Episodes 14–26):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/titans-of-allterra/feeds/season2-part2.xml
```

Season 3, Part 1 (Episodes 1–10):
```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/titans-of-allterra/feeds/season3-part1.xml
```

## Rebuilding the feeds

The feeds are generated from the live source feed
(`https://titansofallterra.libsyn.com/rss`) by `build_feeds.py`:

```
python3 podcasts/titans-of-allterra/build_feeds.py
```

Re-run it if the source feed changes (e.g. episode metadata corrections).

## Source

Podcast: [The Titans of All'Terra](https://titansofallterra.libsyn.com/) by
Joshua Lorimer. This is an unofficial, personal listening aid and
redistributes no audio — feed items link to the original hosted mp3 files.
