#!/usr/bin/env python3
"""
Build custom Yoto-friendly RSS feeds for Tales from the Stinky Dragon,
Campaigns 1 and 2 (both complete).

Why this exists
----------------
Yoto's "custom RSS" card only ever loads the most recent 25 items from a
feed, and plays them back newest-first. This show's real feed mixes each
campaign's main story episodes with "Between the Tales" interlude
episodes (half-numbered, e.g. "C01 - Ep. 08.5 - ... - Between the Tales"),
one-shots, and campaign wrap-up specials -- and its itunes:season/
itunes:episode tags can't be used to cleanly isolate just the main story:
  - itunes:episode numbering for Campaign 1 (season 1) continues straight
    from the story finale (episode 86) into a 3-episode post-finale bonus
    mini-arc ("C01 BONUS - Ep. 01-03 - Infinight Infirms"), numbered
    87-89 as if it were more of the same campaign.
  - Campaign 3 ("C03") is only partially season-tagged -- many of its
    later episodes have no itunes:season tag at all.

So instead of filtering by season, this script matches episode titles
against "C0<campaign> - Ep. <NN> - " (deliberately anchored so it does
NOT match "C01 BONUS - Ep. ..." or ".5"-suffixed interlude episodes,
since there's no bare "- Ep." immediately after "C01"/"C0N " for those)
to build each campaign's canonical episode order directly, ignoring the
season field and excluding interludes/bonus/one-shots by construction.

This script:
  1. Downloads the real feed.
  2. Filters to itunes:episodeType == "full" episodes whose title matches
     the campaign's title pattern.
  3. Splits each campaign's episodes into <=25-item feed "parts" so they
     fit Yoto's limit with headroom (see CAMPAIGNS below).
  4. Re-writes each item's <pubDate> so that, when Yoto sorts newest-first,
     playback order comes out as Episode 1 -> N in-story order within
     each part. The *first* episode of a part gets the newest fake date;
     later episodes get progressively older dates.

Campaign 3 is not covered here -- it's still ongoing as of when this was
written, and its unreliable season tagging plus in-progress episode
count means it needs a fresh look once it wraps.

The original enclosure URLs (actual audio files) and guids are preserved
unchanged -- only channel/item metadata needed for ordering and filtering
is rewritten.

Run:
    python3 podcasts/stinky-dragon/build_feeds.py
"""
from __future__ import annotations

import datetime
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE_FEED_URL = "https://feeds.megaphone.fm/stinkydragon"
OUT_DIR = Path(__file__).resolve().parent / "feeds"

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "googleplay": "http://www.google.com/schemas/play-podcasts/1.0",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

# campaign number -> (title_pattern, parts). Each part is
# (filename, label, first_episode, last_episode).
CAMPAIGNS: dict[int, tuple[re.Pattern, list[tuple[str, str, int, int]]]] = {
    1: (
        re.compile(r"^C01 - Ep\.\s*(\d+)\s*-"),
        [
            ("campaign1-part1.xml", "Campaign 1, Part 1 (Episodes 1-22)", 1, 22),
            ("campaign1-part2.xml", "Campaign 1, Part 2 (Episodes 23-44)", 23, 44),
            ("campaign1-part3.xml", "Campaign 1, Part 3 (Episodes 45-66)", 45, 66),
            ("campaign1-part4.xml", "Campaign 1, Part 4 (Episodes 67-86)", 67, 86),
        ],
    ),
    2: (
        re.compile(r"^C02 - Ep\.\s*(\d+)\s*-"),
        [
            ("campaign2-part1.xml", "Campaign 2, Part 1 (Episodes 1-25)", 1, 25),
            ("campaign2-part2.xml", "Campaign 2, Part 2 (Episodes 26-50)", 26, 50),
        ],
    ),
}

RFC2822 = "%a, %d %b %Y %H:%M:%S +0000"


def fetch_source() -> ET.Element:
    with urllib.request.urlopen(SOURCE_FEED_URL) as resp:
        data = resp.read()
    return ET.fromstring(data)


def campaign_episodes(root: ET.Element, pattern: re.Pattern) -> list[tuple[int, ET.Element]]:
    channel = root.find("channel")
    items = []
    for item in channel.findall("item"):
        ep_type = item.findtext("itunes:episodeType", namespaces=NS)
        title = item.findtext("title") or ""
        m = pattern.match(title)
        if ep_type == "full" and m:
            items.append((int(m.group(1)), item))
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
    title.text = f"Tales from the Stinky Dragon — {title_suffix}"

    link = ET.SubElement(channel, "link")
    link.text = "https://patreon.com/stinkydragon"

    description = ET.SubElement(channel, "description")
    description.text = (
        f"Custom fan-made feed: main story episodes only, in campaign "
        f"order, trimmed for Yoto's 25-track limit. {title_suffix}. "
        f"Original show: Tales from the Stinky Dragon."
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

    for campaign, (pattern, parts) in CAMPAIGNS.items():
        all_eps = dict(campaign_episodes(root, pattern))
        print(f"Found {len(all_eps)} Campaign {campaign} episodes in source feed.")

        for filename, label, lo, hi in parts:
            eps = [(n, all_eps[n]) for n in range(lo, hi + 1) if n in all_eps]
            if len(eps) != (hi - lo + 1):
                missing = set(range(lo, hi + 1)) - {n for n, _ in eps}
                print(f"WARNING: missing episodes in source feed for {filename}: {sorted(missing)}")

            channel = build_channel(source_channel, label)

            # Newest fake pubDate first (Episode `lo`), stepping 1 hour
            # older per subsequent episode, so Yoto's newest-first
            # playback yields correct campaign order.
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
