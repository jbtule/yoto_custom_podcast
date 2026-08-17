#!/usr/bin/env python3
"""
Upload The Titans of All'Terra, Season 1 straight into Yoto's own MYO
("Make Your Own") system as a set of real cards -- no GitHub, no RSS card,
no 25-track limit. Trades that for Yoto's own MYO limits instead:

  - 1 hour max per track       -> episodes over ~55 min get split near a
                                   quiet point close to the midpoint.
  - 6 hours / 500MB max per card -> episodes are greedily packed into as
                                   few cards as those caps allow, in season
                                   order.

Each track also gets a custom 16x16 pixel icon (see icon_gen.py) showing
"S<season>.<card>" over the episode number, e.g. "S1.3 / E18", with an
amber progress line along the bottom for split episodes (half-width for
the first half, full-width for the second).

Local audio is converted to M4A/AAC, not MP3 -- MP3 uploads proved
unreliable through Yoto's own pipeline (confirmed via direct A/B test,
unrelated to anything in this script's API usage). See README.md's "Why
M4A/AAC, not MP3" section for the full story.

Nothing this script downloads, uploads, or caches is committed to git --
see .gitignore. Only your Yoto login token and a small manifest of what's
been uploaded so far live in tools/yoto-uploader/.state/, which is
gitignored.

Usage:
    export YOTO_CLIENT_ID=<your client id from https://dashboard.yoto.dev/>
    python3 build_titans_season1.py --dry-run     # show the card plan only
    python3 build_titans_season1.py                # do it for real
    python3 build_titans_season1.py                # safe to re-run any time

Requires ffmpeg/ffprobe on PATH (`brew install ffmpeg`).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET

from icon_gen import save_icon
from yoto_auth import get_access_token
from yoto_client import YotoClient

SOURCE_FEED_URL = "https://titansofallterra.libsyn.com/rss"
NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, ".state")
WORK_DIR = os.path.join(STATE_DIR, "work", "titans-season1")
MANIFEST_PATH = os.path.join(STATE_DIR, "titans-season1-manifest.json")

MAX_TRACK_SEC = 60 * 60          # Yoto per-track cap
SPLIT_THRESHOLD_SEC = 55 * 60    # split earlier than the hard cap, with margin
MAX_CARD_SEC = 6 * 60 * 60       # Yoto per-card cap
MAX_CARD_BYTES = 500 * 1024 * 1024

SEASON = 1
CARD_TITLE_PREFIX = "The Titans of All'Terra — S1"


# --------------------------------------------------------------------------
# Source feed
# --------------------------------------------------------------------------

def fetch_channel_image_url() -> str | None:
    with urllib.request.urlopen(SOURCE_FEED_URL) as resp:
        root = ET.fromstring(resp.read())
    image = root.find("channel").find("image")
    return image.findtext("url") if image is not None else None


def fetch_season1_episodes() -> list[dict]:
    with urllib.request.urlopen(SOURCE_FEED_URL) as resp:
        root = ET.fromstring(resp.read())
    episodes = []
    for item in root.find("channel").findall("item"):
        ep_type = item.findtext("itunes:episodeType", namespaces=NS)
        season = item.findtext("itunes:season", namespaces=NS)
        episode = item.findtext("itunes:episode", namespaces=NS)
        if ep_type != "full" or season != "1" or not episode:
            continue
        enclosure = item.find("enclosure")
        episodes.append(
            {
                "episode": int(episode),
                "title": item.findtext("title"),
                "audio_url": enclosure.get("url"),
                "approx_size": int(enclosure.get("length", 0)),
            }
        )
    episodes.sort(key=lambda e: e["episode"])
    return episodes


# --------------------------------------------------------------------------
# Local audio processing
# --------------------------------------------------------------------------

def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg/ffprobe not found on PATH. Install with: brew install ffmpeg")


def ffprobe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def download(url: str, dest: str):
    if os.path.exists(dest):
        return
    tmp = dest + ".part"
    urllib.request.urlretrieve(url, tmp)
    # These source mp3s carry an embedded cover-art image as a second
    # (video) stream alongside the audio, and Yoto's own MP3 ingest
    # pipeline turned out to be unreliable for us regardless of how
    # carefully the mp3 was re-encoded (VBR headers, ID3 size, etc. all
    # checked out fine locally, but standalone-upload tests through the
    # official Yoto app still played a few seconds then cut off/crashed).
    # Confirmed via direct A/B test that the same audio re-encoded as
    # M4A/AAC uploads and plays correctly, so we convert straight to M4A
    # here rather than staying on MP3 at all.
    stripped = dest + ".stripped"
    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp, "-map", "0:a:0", "-c:a", "aac", "-b:a", "128k", "-vn", "-f", "mp4", stripped],
        capture_output=True, check=True,
    )
    os.remove(tmp)
    os.rename(stripped, dest)


def find_split_point(path: str, duration: float) -> float:
    """Pick a quiet-ish moment nearest the midpoint to split on."""
    proc = subprocess.run(
        ["ffmpeg", "-i", path, "-af", "silencedetect=noise=-30dB:d=0.5", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    midpoint = duration / 2
    lo, hi = duration * 0.3, duration * 0.7
    best, best_dist = None, None
    for line in proc.stderr.splitlines():
        if "silence_start" in line:
            t = float(line.split("silence_start:")[1].strip())
            if lo <= t <= hi:
                dist = abs(t - midpoint)
                if best_dist is None or dist < best_dist:
                    best, best_dist = t, dist
    return best if best is not None else midpoint


def split_audio(path: str, split_at: float, out_a: str, out_b: str):
    if os.path.exists(out_a) and os.path.exists(out_b):
        return
    subprocess.run(
        ["ffmpeg", "-y", "-i", path, "-to", f"{split_at}", "-c:a", "aac", "-b:a", "128k", "-f", "mp4", out_a],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", path, "-ss", f"{split_at}", "-c:a", "aac", "-b:a", "128k", "-f", "mp4", out_b],
        capture_output=True, check=True,
    )


def prepare_episode_tracks(ep: dict) -> list[dict]:
    """Download an episode and return 1-2 local track dicts (title, path, part)."""
    os.makedirs(WORK_DIR, exist_ok=True)
    base = f"ep{ep['episode']:02d}"
    raw_path = os.path.join(WORK_DIR, base + ".m4a")
    download(ep["audio_url"], raw_path)
    duration = ffprobe_duration(raw_path)

    if duration <= SPLIT_THRESHOLD_SEC:
        return [{"title": ep["title"], "path": raw_path, "duration": duration, "part": None}]

    split_at = find_split_point(raw_path, duration)
    part_a = os.path.join(WORK_DIR, base + "a.m4a")
    part_b = os.path.join(WORK_DIR, base + "b.m4a")
    split_audio(raw_path, split_at, part_a, part_b)
    dur_a = ffprobe_duration(part_a)
    dur_b = ffprobe_duration(part_b)
    return [
        {"title": f"{ep['title']} (Part 1)", "path": part_a, "duration": dur_a, "part": 1},
        {"title": f"{ep['title']} (Part 2)", "path": part_b, "duration": dur_b, "part": 2},
    ]


# --------------------------------------------------------------------------
# Icons
# --------------------------------------------------------------------------

ICON_DIR = os.path.join(WORK_DIR, "icons")


def prepare_icon(card_index: int, episode_num: int, part: int | None) -> str:
    os.makedirs(ICON_DIR, exist_ok=True)
    suffix = f"_p{part}" if part else ""
    path = os.path.join(ICON_DIR, f"c{card_index:02d}_e{episode_num:02d}{suffix}.png")
    if not os.path.exists(path):
        save_icon(SEASON, card_index, episode_num, path, part=part)
    return path


# --------------------------------------------------------------------------
# Card packing (planning only -- uses feed-reported size/duration, which is
# what the real audio matches closely enough to plan card boundaries with)
# --------------------------------------------------------------------------

def pack_into_cards(episodes: list[dict]) -> list[list[dict]]:
    cards, current, cur_sec, cur_bytes = [], [], 0, 0
    for ep in episodes:
        dur = ep.get("approx_duration") or 0
        size = ep["approx_size"]
        if current and (cur_sec + dur > MAX_CARD_SEC or cur_bytes + size > MAX_CARD_BYTES):
            cards.append(current)
            current, cur_sec, cur_bytes = [], 0, 0
        current.append(ep)
        cur_sec += dur
        cur_bytes += size
    if current:
        cards.append(current)
    return cards


def fetch_approx_durations(episodes: list[dict]):
    """Fill in approx_duration (seconds) from itunes:duration for planning."""
    with urllib.request.urlopen(SOURCE_FEED_URL) as resp:
        root = ET.fromstring(resp.read())
    by_ep = {}
    for item in root.find("channel").findall("item"):
        episode = item.findtext("itunes:episode", namespaces=NS)
        if not episode:
            continue
        d = item.findtext("itunes:duration", namespaces=NS)
        parts = [int(x) for x in d.split(":")]
        if len(parts) == 3:
            h, m, s = parts
        elif len(parts) == 2:
            h, m, s = 0, *parts
        else:
            h, m, s = 0, 0, parts[0]
        by_ep[int(episode)] = h * 3600 + m * 60 + s
    for ep in episodes:
        ep["approx_duration"] = by_ep.get(ep["episode"], 0)


# --------------------------------------------------------------------------
# Manifest (idempotency across re-runs)
# --------------------------------------------------------------------------

def load_manifest() -> dict:
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
        manifest.setdefault("icons", {})
        return manifest
    return {"episodes": {}, "cards": {}, "icons": {}}


def save_manifest(manifest: dict):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


# --------------------------------------------------------------------------
# Upload + card creation
# --------------------------------------------------------------------------

def upload_track(client: YotoClient, local_track: dict, card_index: int, episode_num: int, manifest: dict) -> dict:
    # Icon prep/upload is independent of the audio cache below -- it has
    # its own cache (manifest["icons"], keyed by icon filename) so a
    # from-scratch icon redesign can be picked up on a re-run without
    # needing to re-upload already-cached audio too.
    icon_path = prepare_icon(card_index, episode_num, local_track["part"])
    icon_key = os.path.basename(icon_path)
    icon_media_id = manifest["icons"].get(icon_key)
    if not icon_media_id:
        icon_media_id = client.upload_icon(icon_path, icon_key)
        manifest["icons"][icon_key] = icon_media_id
        save_manifest(manifest)

    key = local_track["path"]
    cached = manifest["episodes"].get(key)
    if cached:
        if cached.get("icon_media_id") != icon_media_id:
            cached["icon_media_id"] = icon_media_id
            save_manifest(manifest)
        return cached

    def progress(msg):
        print(f"    {local_track['title']}: {msg}")

    info = client.upload_audio(local_track["path"], on_progress=progress)

    channels = info.get("channels") or "stereo"
    channels = {1: "mono", 2: "stereo"}.get(channels, channels)  # API may return numeric channel counts

    track = {
        "title": local_track["title"],
        "trackUrl": f"yoto:#{info['transcodedSha256']}",
        "format": info.get("format") or "aac",
        "duration": info.get("duration") or local_track["duration"],
        "fileSize": info.get("fileSize") or os.path.getsize(local_track["path"]),
        "channels": channels,
        "icon_media_id": icon_media_id,
    }
    manifest["episodes"][key] = track
    save_manifest(manifest)
    return track


def build_card_content(card_index: int, episodes: list[dict], local_tracks_by_ep: dict, cover_url: str | None,
                        existing_card_id: str | None = None, title_suffix: str = "") -> dict:
    chapters = []
    card_duration = 0
    card_filesize = 0
    for i, ep in enumerate(episodes, start=1):
        tracks = local_tracks_by_ep[ep["episode"]]
        chapter_key = f"{i:02d}"
        chapter_duration = sum(t["duration"] for t in tracks)
        chapter_filesize = sum(t["fileSize"] for t in tracks)
        card_duration += chapter_duration
        card_filesize += chapter_filesize
        chapters.append(
            {
                "key": chapter_key,
                "title": ep["title"],
                "tracks": [
                    {
                        "key": f"{chapter_key}-{j:02d}",
                        "uid": f"c{chapter_key}t{j:02d}",
                        "type": "audio",
                        "format": t["format"],
                        "title": t["title"],
                        "trackUrl": t["trackUrl"],
                        "duration": t["duration"],
                        "fileSize": t["fileSize"],
                        "channels": t.get("channels", "stereo"),
                        "display": {"icon16x16": f"yoto:#{t['icon_media_id']}"},
                        "overlayLabel": str(j),
                    }
                    for j, t in enumerate(tracks, start=1)
                ],
                # Chapter-level aggregates -- not just cosmetic. Suspected
                # necessary for the physical player's download/playback
                # gating (it showed complete downloads but silent playback
                # on every chapter until these were added; cloud streaming
                # via the app worked the whole time, which fits since that
                # path wouldn't depend on pre-aggregated duration/fileSize).
                "duration": chapter_duration,
                "fileSize": chapter_filesize,
                "defaultTrackDisplay": f"{chapter_key}-01",
                "defaultTrackAmbient": f"{chapter_key}-01",
                "display": {"icon16x16": f"yoto:#{tracks[0]['icon_media_id']}"},
            }
        )
    first_ep, last_ep = episodes[0]["episode"], episodes[-1]["episode"]
    # NOTE: category "podcast" is for Yoto's own RSS-feed-linked podcast
    # cards (streamed, not downloaded for offline play) -- "stories" is
    # correct for MYO cards with uploaded audio, which need to actually
    # download onto the device.
    metadata = {
        "category": "stories",
        "languages": ["en"],
        "media": {"duration": card_duration, "fileSize": card_filesize, "hasStreams": False},
    }
    if cover_url:
        metadata["cover"] = {"imageL": cover_url}
    payload = {
        "title": f"{CARD_TITLE_PREFIX} Card {card_index} (Episodes {first_ep}-{last_ep}){title_suffix}",
        "content": {
            "chapters": chapters,
            "playbackType": "linear",
        },
        "metadata": metadata,
    }
    if existing_card_id:
        payload["cardId"] = existing_card_id
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print the card plan and exit; no downloads/uploads.")
    parser.add_argument("--force-login", action="store_true", help="Ignore any cached Yoto session and log in again.")
    parser.add_argument("--only-card", type=int, help="Only process this card number (1-based).")
    parser.add_argument("--force-recreate", action="store_true",
                         help="Re-run an already-created card (e.g. --only-card 3), updating it in "
                              "place via its existing cardId instead of skipping or duplicating it.")
    parser.add_argument("--as-new-card", action="store_true",
                         help="Force a genuine create (no cardId) even if this card number was already "
                              "created before, and record it under a separate manifest key ('<N>-new') "
                              "so the original card's record is untouched. For diagnosing whether a "
                              "problem is specific to an existing card's update history.")
    args = parser.parse_args()

    episodes = fetch_season1_episodes()
    fetch_approx_durations(episodes)
    print(f"Found {len(episodes)} Season 1 full episodes.")

    cards = pack_into_cards(episodes)
    print(f"Planned {len(cards)} card(s):")
    for i, card in enumerate(cards, start=1):
        total_sec = sum(e["approx_duration"] for e in card)
        total_mb = sum(e["approx_size"] for e in card) / 1024 / 1024
        eps = [e["episode"] for e in card]
        print(f"  Card {i}: episodes {eps[0]}-{eps[-1]} ({len(eps)} eps, "
              f"~{total_sec/3600:.2f}h, ~{total_mb:.0f}MB)")

    if args.dry_run:
        return

    require_ffmpeg()
    manifest = load_manifest()
    token = get_access_token(force_login=args.force_login)
    client = YotoClient(token)

    cover_url = manifest.get("cover_url")
    if not cover_url:
        source_image_url = fetch_channel_image_url()
        if source_image_url:
            print(f"Uploading podcast cover art from {source_image_url} ...")
            cover_url = client.upload_cover_image(source_image_url)
            manifest["cover_url"] = cover_url
            save_manifest(manifest)

    for i, card in enumerate(cards, start=1):
        if args.only_card and i != args.only_card:
            continue
        card_key = f"{i}-new" if args.as_new_card else str(i)
        existing_card_id = None if args.as_new_card else manifest["cards"].get(card_key, {}).get("cardId")
        if existing_card_id and not args.force_recreate:
            print(f"Card {i} already created: {existing_card_id} -- skipping.")
            continue

        print(f"\n=== Card {i}: episodes {card[0]['episode']}-{card[-1]['episode']} ===")
        local_tracks_by_ep = {}
        for ep in card:
            print(f"  Preparing episode {ep['episode']}: {ep['title']}")
            local_tracks_by_ep[ep["episode"]] = prepare_episode_tracks(ep)

        uploaded_tracks_by_ep = {}
        for ep in card:
            uploaded_tracks_by_ep[ep["episode"]] = [
                upload_track(client, t, i, ep["episode"], manifest)
                for t in local_tracks_by_ep[ep["episode"]]
            ]

        title_suffix = " [TEST]" if args.as_new_card else ""
        content = build_card_content(i, card, uploaded_tracks_by_ep, cover_url, existing_card_id, title_suffix)
        print(f"  Creating card '{content['title']}'...")
        result = client.create_or_update_content(content)
        card_id = result.get("cardId") or result.get("card", {}).get("cardId")
        manifest["cards"][card_key] = {"cardId": card_id, "title": content["title"]}
        save_manifest(manifest)
        print(f"  Created: {card_id}")

    print("\nDone. Cards should now show up under My Cards in the Yoto app.")


if __name__ == "__main__":
    main()
