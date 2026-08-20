# Yoto Custom Podcasts

Two ways to get podcasts onto a [Yoto Player](https://yotoplay.com/):

- **[`podcasts/`](podcasts/)** — Custom RSS feeds, trimmed and reordered to
  work around Yoto's custom-RSS-card quirks (only the latest 25 feed items
  load, and they play back newest → oldest). Feeds are published on GitHub
  Pages/raw URLs; no audio is hosted here.
- **[`tools/yoto-uploader/`](tools/yoto-uploader/)** — Uploads audio
  directly into Yoto's own MYO system via the Yoto API, creating real cards
  in your library instead of a custom-RSS card. Works around MYO's own
  limits (1h/track, 6h & 500MB/card) instead of the RSS ones. Nothing it
  downloads or uploads is ever committed to git.

Each podcast gets its own folder under `podcasts/`.

## Podcasts

- [`podcasts/titans-of-allterra`](podcasts/titans-of-allterra) — *The Titans
  of All'Terra*, Seasons 1 & 2, each split into two feeds, story episodes
  only, in correct season order.
- [`podcasts/tales-of-bob`](podcasts/tales-of-bob) — *Tales of Bob*'s
  "Broken Tusk Rising" campaign (93 chapters), split into four feeds,
  side-content/one-shots excluded, in correct chapter order.
- [`podcasts/sneak-attack`](podcasts/sneak-attack) — *Sneak Attack!*,
  Season 1 (156 episodes), split into seven feeds, story episodes only,
  in correct season order.
- [`podcasts/dungeons-dragons-daughters`](podcasts/dungeons-dragons-daughters) —
  *Dungeons & Dragons & Daughters*, Campaign 1 (70 chapters, complete),
  split into three feeds, bonus/recap episodes and the ongoing Campaign 2
  excluded, in correct chapter order.

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
