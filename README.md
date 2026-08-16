# Yoto Custom Podcasts

Custom RSS feeds for loading podcasts onto a [Yoto Player](https://yotoplay.com/)
via its custom RSS card — trimmed and reordered to work around Yoto's quirks
(only the latest 25 feed items load, and they play back newest → oldest).

Each podcast gets its own folder under `podcasts/`.

## Podcasts

- [`podcasts/titans-of-allterra`](podcasts/titans-of-allterra) — *The Titans
  of All'Terra*, Seasons 1 & 2, each split into two feeds, story episodes
  only, in correct season order.

## Layout convention

```
podcasts/<podcast-slug>/
  README.md        — what this podcast's feeds are and how to use them
  build_feeds.py    — script that (re)generates the feeds from the source RSS
  feeds/*.xml       — the generated, Yoto-ready feed files
```

Raw feed URLs for Yoto follow the pattern:

```
https://raw.githubusercontent.com/jbtule/yoto_custom_podcast/main/podcasts/<podcast-slug>/feeds/<file>.xml
```
