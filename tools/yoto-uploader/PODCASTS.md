# Configured podcasts

Snapshot of every podcast+season currently configured in `podcasts.yaml`,
from `--dry-run` (no audio downloaded/uploaded, no cards created for any
of these yet). Card counts are the MYO planning estimate — 1h/track,
6h & 500MB/card caps.

| Podcast | Season/Campaign | Episodes | Total Hours | Cards |
|---|---|---:|---:|---:|
| Titans of All'Terra | S1 | 36 | 35.2h | 7 |
| Titans of All'Terra | S2 | 26 | 23.8h | 5 |
| Tales of Bob | Broken Tusk Rising | 93 | 87.7h | 16 |
| Sneak Attack! | S1 | 156 | 155.7h | 29 |
| Dungeons & Dragons & Daughters | Campaign 1 | 70 | 77.5h | 15 |
| Tales from the Stinky Dragon | Campaign 1 | 86 | 106.7h | 21 |
| Tales from the Stinky Dragon | Campaign 2 | 50 | 70.1h | 13 |
| **Total** | | **517** | **556.7h** | **86** |

Regenerate this table (episode counts/hours can drift if a source feed
changes, or once `local_feed_paths` picks up newly-added RSS feed parts):

```
python3 -c "
import build_cards as b
config = b.load_podcasts_config()
for name, entry in config.items():
    for season in sorted(set(entry.get('icon_palettes', {})) | set(entry.get('local_feed_paths', {}))):
        b.configure_for_podcast(name, season, config)
        episodes = b.fetch_season_episodes()
        b.fetch_approx_durations(episodes)
        total_h = sum(e['approx_duration'] for e in episodes) / 3600
        cards = b.pack_into_cards(episodes)
        print(f'{name} s{season}: {len(episodes)} eps, {total_h:.1f}h, {len(cards)} cards')
"
```

See `podcasts.yaml` for the config schema, and each show's
`podcasts/<slug>/README.md` for what's included/excluded and why.
