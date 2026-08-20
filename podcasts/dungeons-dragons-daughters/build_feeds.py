#!/usr/bin/env python3
"""
Build custom Yoto-friendly RSS feeds for Dungeons & Dragons & Daughters,
Campaign 1 (chapters 0-69, the show's first, now-complete campaign).

Why this exists
----------------
Yoto's "custom RSS" card only ever loads the most recent 25 items from a
feed, and plays them back newest-first. This show's real feed has almost
no usable itunes:season tagging at all (108 of 110 items are untagged --
only 2 stray items carry a season tag, not enough to filter by). What the
feed DOES have reliably is a leading sequential number in each story
episode's title ("N. DDD <arc name>"), which this script matches via
regex instead. Titles without that leading number ("DDD Out of the
Dungeon - N" recap episodes, specials, a cross-promo bonus) are bonus/
side content, correctly excluded by not matching the pattern.

The numbered sequence itself spans two distinct campaigns: chapters 0-69
(this script's scope) form the complete first campaign, ending at
"69. DDD Our First Campaign Wrap!"; chapters 70+ are a second, still-
ongoing campaign ("The Wild Beyond the Witchlight") not covered here.

This script:
  1. Downloads the real feed.
  2. Filters to itunes:episodeType == "full" episodes whose title matches
     the leading-number pattern, restricted to chapters 0-69.
  3. Splits the 70 chapters into <=25-item feed "parts" so they fit
     Yoto's limit with headroom (see PARTS below).
  4. Re-writes each item's <pubDate> so that, when Yoto sorts newest-first,
     playback order comes out as Chapter 0 -> N in-story order within
     each part. The *first* chapter of a part gets the newest fake date;
     later chapters get progressively older dates.

The original enclosure URLs (actual audio files) and guids are preserved
unchanged -- only channel/item metadata needed for ordering and filtering
is rewritten.

Run:
    python3 podcasts/dungeons-dragons-daughters/build_feeds.py
"""
from __future__ import annotations

import datetime
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE_FEED_URL = "https://feed.podbean.com/dungeonsdragonsdaughters/feed.xml"
OUT_DIR = Path(__file__).resolve().parent / "feeds"

CHAPTER_TITLE_RE = re.compile(r"^(\d+)\.\s+DDD\s+.+$")

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

# list of (filename, label, first_chapter, last_chapter)
PARTS: list[tuple[str, str, int, int]] = [
    ("campaign1-part1.xml", "Campaign 1, Part 1 (Chapters 0-23)", 0, 23),
    ("campaign1-part2.xml", "Campaign 1, Part 2 (Chapters 24-46)", 24, 46),
    ("campaign1-part3.xml", "Campaign 1, Part 3 (Chapters 47-69)", 47, 69),
]

RFC2822 = "%a, %d %b %Y %H:%M:%S +0000"


def fetch_source() -> ET.Element:
    with urllib.request.urlopen(SOURCE_FEED_URL) as resp:
        data = resp.read()
    return ET.fromstring(data)


def campaign1_chapters(root: ET.Element) -> list[tuple[int, ET.Element]]:
    channel = root.find("channel")
    items = []
    for item in channel.findall("item"):
        ep_type = item.findtext("itunes:episodeType", namespaces=NS)
        title = item.findtext("title") or ""
        m = CHAPTER_TITLE_RE.match(title)
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
    title.text = f"Dungeons & Dragons & Daughters — {title_suffix}"

    link = ET.SubElement(channel, "link")
    link.text = "https://dungeonsdragonsdaughters.podbean.com/"

    description = ET.SubElement(channel, "description")
    description.text = (
        f"Custom fan-made feed: Campaign 1 story episodes only, in "
        f"chapter order, trimmed for Yoto's 25-track limit. {title_suffix}. "
        f"Original show: Dungeons & Dragons & Daughters, Block Party "
        f"Podcast Network."
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

    all_chapters = dict(campaign1_chapters(root))
    print(f"Found {len(all_chapters)} numbered story chapters in source feed (all campaigns).")

    for filename, label, lo, hi in PARTS:
        eps = [(n, all_chapters[n]) for n in range(lo, hi + 1) if n in all_chapters]
        if len(eps) != (hi - lo + 1):
            missing = set(range(lo, hi + 1)) - {n for n, _ in eps}
            print(f"WARNING: missing chapters in source feed for {filename}: {sorted(missing)}")

        channel = build_channel(source_channel, label)

        # Newest fake pubDate first (Chapter `lo`), stepping 1 hour older
        # per subsequent chapter, so Yoto's newest-first playback yields
        # correct campaign order.
        base = datetime.datetime.now(datetime.timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        for offset, (chapter_num, item) in enumerate(eps):
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
        print(f"Wrote {out_path} ({len(eps)} chapters, {label})")


if __name__ == "__main__":
    main()
