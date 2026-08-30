#!/usr/bin/env python3
"""
Build custom Yoto-friendly RSS feeds for The Titans of All'Terra.

Why this exists
----------------
Yoto's "custom RSS" card only ever loads the most recent 25 items from a
feed, and plays them back newest-first. Every season of the source podcast
mixes story episodes with non-episode bonus tracks (cast intros, autopsies,
Kickstarter plugs, etc), and several seasons have more than 25 story
episodes. This script:

  1. Downloads the real feed.
  2. Filters down to a given season, itunes:episodeType == "full" only.
  3. Splits each season into <=25-item feed "parts" so they fit Yoto's
     limit with headroom (see SEASONS below for the exact split per
     season).
  4. Re-writes each item's <pubDate> so that, when Yoto sorts newest-first,
     playback order comes out as Episode 1 -> N in-story order within each
     part. The *first* episode of a part gets the newest fake date; later
     episodes get progressively older dates.

The original enclosure URLs (actual audio files) and guids are preserved
unchanged -- only channel/item metadata needed for ordering and filtering
is rewritten.

Run:
    python3 podcasts/titans-of-allterra/build_feeds.py
"""
from __future__ import annotations

import datetime
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE_FEED_URL = "https://titansofallterra.libsyn.com/rss"
OUT_DIR = Path(__file__).resolve().parent / "feeds"

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "podcast": "https://podcastindex.org/namespace/1.0",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

# season -> list of (filename, label, first_episode, last_episode)
SEASONS: dict[int, list[tuple[str, str, int, int]]] = {
    1: [
        ("season1-part1.xml", "Season 1, Part 1 (Episodes 1-18)", 1, 18),
        ("season1-part2.xml", "Season 1, Part 2 (Episodes 19-36)", 19, 36),
    ],
    2: [
        ("season2-part1.xml", "Season 2, Part 1 (Episodes 1-13)", 1, 13),
        ("season2-part2.xml", "Season 2, Part 2 (Episodes 14-26)", 14, 26),
    ],
    3: [
        ("season3-part1.xml", "Season 3, Part 1 (Episodes 1-10)", 1, 10),
    ],
}

RFC2822 = "%a, %d %b %Y %H:%M:%S +0000"


def fetch_source() -> ET.Element:
    with urllib.request.urlopen(SOURCE_FEED_URL) as resp:
        data = resp.read()
    return ET.fromstring(data)


def season_full_episodes(root: ET.Element, season: int) -> list[tuple[int, ET.Element]]:
    channel = root.find("channel")
    items = []
    for item in channel.findall("item"):
        ep_type = item.findtext("itunes:episodeType", namespaces=NS)
        item_season = item.findtext("itunes:season", namespaces=NS)
        episode = item.findtext("itunes:episode", namespaces=NS)
        if ep_type == "full" and item_season == str(season) and episode:
            items.append((int(episode), item))
    items.sort(key=lambda pair: pair[0])
    return items


def build_channel(source_channel: ET.Element, title_suffix: str) -> ET.Element:
    channel = ET.Element("channel")

    def copy_tag(tag: str, ns_key: str | None = None):
        full_tag = f"{{{NS[ns_key]}}}{tag}" if ns_key else tag
        el = source_channel.find(full_tag)
        if el is not None:
            channel.append(el)

    title = ET.SubElement(channel, "title")
    title.text = f"The Titans of All'Terra — {title_suffix}"

    link = ET.SubElement(channel, "link")
    link.text = "https://titansofallterra.libsyn.com/"

    description = ET.SubElement(channel, "description")
    description.text = (
        f"Custom fan-made feed: story episodes only, in season order, "
        f"trimmed for Yoto's 25-track limit. {title_suffix}. "
        f"Original show: The Titans of All'Terra by Joshua Lorimer."
    )

    lang = ET.SubElement(channel, "language")
    lang.text = "en"

    copy_tag("image")
    copy_tag("author", "itunes")
    copy_tag("category", "itunes")
    copy_tag("explicit", "itunes")

    img = source_channel.find("image")
    if img is not None:
        itunes_image = ET.SubElement(channel, "{%s}image" % NS["itunes"])
        url_el = img.find("url")
        if url_el is not None and url_el.text:
            itunes_image.set("href", url_el.text)

    now = datetime.datetime.now(datetime.timezone.utc)
    pub = ET.SubElement(channel, "pubDate")
    pub.text = now.strftime(RFC2822)
    last_build = ET.SubElement(channel, "lastBuildDate")
    last_build.text = now.strftime(RFC2822)

    return channel


def main() -> None:
    root = fetch_source()
    source_channel = root.find("channel")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for season, parts in SEASONS.items():
        all_eps = dict(season_full_episodes(root, season))
        print(f"Found {len(all_eps)} Season {season} full episodes in source feed.")

        for filename, label, lo, hi in parts:
            eps = [(n, all_eps[n]) for n in range(lo, hi + 1) if n in all_eps]
            if len(eps) != (hi - lo + 1):
                missing = set(range(lo, hi + 1)) - {n for n, _ in eps}
                print(f"WARNING: missing episodes in source feed for {filename}: {sorted(missing)}")

            channel = build_channel(source_channel, label)

            # Newest fake pubDate first (Episode `lo`), stepping 1 hour older
            # per subsequent episode, so Yoto's newest-first playback yields
            # correct season order.
            base = datetime.datetime.now(datetime.timezone.utc).replace(
                minute=0, second=0, microsecond=0
            )
            for offset, (ep_num, item) in enumerate(eps):
                fake_date = base - datetime.timedelta(hours=offset)
                pubdate_el = item.find("pubDate")
                if pubdate_el is None:
                    pubdate_el = ET.SubElement(item, "pubDate")
                pubdate_el.text = fake_date.strftime(RFC2822)
                channel.append(item)

            rss = ET.Element("rss", {"version": "2.0"})
            rss.append(channel)

            tree = ET.ElementTree(rss)
            ET.indent(tree, space="  ")
            out_path = OUT_DIR / filename
            tree.write(out_path, encoding="UTF-8", xml_declaration=True)
            print(f"Wrote {out_path} ({len(eps)} episodes, {label})")


if __name__ == "__main__":
    main()
