#!/usr/bin/env python3
"""
Upload a podcast season straight into Yoto's own MYO ("Make Your Own")
system as a set of real cards -- no GitHub, no RSS card, no 25-track
limit. Trades that for Yoto's own MYO limits instead:

  - 1 hour max per track       -> episodes over ~55 min get split near a
                                   quiet point close to the midpoint.
  - 6 hours / 500MB max per card -> episodes are greedily packed into as
                                   few cards as those caps allow, in season
                                   order.

Which podcast/season to build is picked with --podcast/--season; the
podcast is looked up in podcasts.yaml (see that file for the config
schema and how to add a new show). Nothing here is specific to any one
podcast.

Each track also gets a custom 16x16 pixel icon (see icon_gen.py) showing
"S<season>.<card>" over the episode number, e.g. "S1.3 / E18", colored
per the podcast's configured icon_palette, with an amber progress line
along the bottom for split episodes (blank for the first half, half-width
for the second).

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
    python3 build_cards.py --list-podcasts                       # show configured podcasts
    python3 build_cards.py --podcast titans --season 1 --dry-run  # show the card plan only
    python3 build_cards.py --podcast titans --season 1             # do it for real
    python3 build_cards.py --podcast titans --season 1             # safe to re-run any time

Requires ffmpeg/ffprobe on PATH (`brew install ffmpeg`).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET

import yaml
from PIL import Image

import ad_strip
from icon_gen import apply_cover_badge, pad_to_safe_portrait, save_icon
from yoto_auth import get_access_token
from yoto_client import YotoClient

NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}

# Some podcast-tracking redirect chains (podtrac, megaphone, etc.) 403 the
# stock "Python-urllib/x.y" User-Agent specifically, but accept literally
# any other one -- so install a global opener that sends a normal-looking
# UA on every urllib.request call in this file (feed fetch, audio
# download, cover art fetch).
_opener = urllib.request.build_opener()
_opener.addheaders = [("User-Agent", "yoto-custom-podcast-uploader/1.0")]
urllib.request.install_opener(_opener)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))  # tools/yoto-uploader -> repo root
STATE_DIR = os.path.join(HERE, ".state")
PODCASTS_CONFIG_PATH = os.path.join(HERE, "podcasts.yaml")

MAX_TRACK_SEC = 60 * 60          # Yoto per-track cap
SPLIT_THRESHOLD_SEC = 55 * 60    # split earlier than the hard cap, with margin
MAX_CARD_SEC = 6 * 60 * 60       # Yoto per-card cap
MAX_CARD_BYTES = 500 * 1024 * 1024

# Populated in main() from podcasts.yaml for the selected --podcast; the
# rest of this script reads them as module-level config, same pattern as
# the WORK_DIR/MANIFEST_PATH/ICON_DIR paths below.
FEED_URL: str = ""
SEASON: int = 0
CARD_TITLE_PREFIX: str = ""
ICON_PALETTE: str = "original"
STRIP_ADS: str | None = None  # None, "dynamic", or "leading" -- see ad_strip.py
TITLE_PATTERN: re.Pattern | None = None
LOCAL_FEED_PATHS: list[str] = []
WORK_DIR: str = ""
MANIFEST_PATH: str = ""
ICON_DIR: str = ""


def load_podcasts_config() -> dict:
    with open(PODCASTS_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def configure_for_podcast(short_name: str, season: int, config: dict):
    """Set the module-level config globals for the selected podcast+season."""
    global FEED_URL, SEASON, CARD_TITLE_PREFIX, ICON_PALETTE, STRIP_ADS, TITLE_PATTERN, LOCAL_FEED_PATHS
    global WORK_DIR, MANIFEST_PATH, ICON_DIR, _source_cache
    _source_cache = None
    entry = config[short_name]
    FEED_URL = entry["feed_url"]
    SEASON = season
    CARD_TITLE_PREFIX = f"{entry['title']} — S{season}"
    ICON_PALETTE = entry.get("icon_palette", "original")
    STRIP_ADS = entry.get("strip_ads") or None
    if STRIP_ADS not in (None, "dynamic", "leading", "megaphone-header"):
        raise SystemExit(f"{short_name}: strip_ads must be 'megaphone-header', 'dynamic', 'leading', "
                          f"or unset, got {STRIP_ADS!r}")
    pattern_str = entry.get("title_patterns", {}).get(season)
    TITLE_PATTERN = re.compile(pattern_str) if pattern_str else None
    LOCAL_FEED_PATHS = entry.get("local_feed_paths", {}).get(season, [])
    state_key = f"{short_name}-s{season}"
    WORK_DIR = os.path.join(STATE_DIR, "work", state_key)
    MANIFEST_PATH = os.path.join(STATE_DIR, f"{state_key}-manifest.json")
    ICON_DIR = os.path.join(WORK_DIR, "icons")


# --------------------------------------------------------------------------
# Source feed
# --------------------------------------------------------------------------

_source_cache: tuple[ET.Element, list[ET.Element]] | None = None


def _fetch_channel_and_items() -> tuple[ET.Element, list[ET.Element]]:
    """Fetch the source channel + all its items -- either the single
    external FEED_URL, or (when podcasts.yaml configures local_feed_paths
    for this season) our own already-filtered/reordered custom RSS feed
    parts from podcasts/<slug>/feeds/, merged. Using our own feeds avoids
    re-deriving the same season-tag-unreliability workarounds twice (the
    filtering already happened when those feeds were built) and is more
    robust -- no dependency on the original host feed staying up or
    unchanged. Cached per process since this is called from multiple
    places.
    """
    global _source_cache
    if _source_cache is not None:
        return _source_cache

    if LOCAL_FEED_PATHS:
        channel = None
        items = []
        for rel_path in LOCAL_FEED_PATHS:
            part_channel = ET.parse(os.path.join(REPO_ROOT, rel_path)).getroot().find("channel")
            if channel is None:
                channel = part_channel
            items.extend(part_channel.findall("item"))
    else:
        with urllib.request.urlopen(FEED_URL) as resp:
            root = ET.fromstring(resp.read())
        channel = root.find("channel")
        items = channel.findall("item")

    _source_cache = (channel, items)
    return _source_cache


def fetch_channel_image_url() -> str | None:
    channel, _ = _fetch_channel_and_items()
    image = channel.find("image")
    return image.findtext("url") if image is not None else None


def _episode_number_for_item(item: ET.Element) -> int | None:
    """Pick out this item's episode number, two ways:

    - Normally, the feed's own itunes:episode tag, restricted to items
      tagged with the season we're building (itunes:season).
    - If the podcast config set a title_patterns regex for this season
      (see podcasts.yaml), match against the title instead and use the
      pattern's one capture group as the episode number. For shows whose
      season/episode tags are inconsistent or don't isolate the content
      we actually want (e.g. Tales of Bob's "Broken Tusk Rising"
      campaign spans several inconsistently-tagged/untagged "seasons"),
      this is the only reliable way to build a clean episode sequence.
    """
    if TITLE_PATTERN:
        m = TITLE_PATTERN.match(item.findtext("title") or "")
        return int(m.group(1)) if m else None
    season = item.findtext("itunes:season", namespaces=NS)
    episode = item.findtext("itunes:episode", namespaces=NS)
    if season != str(SEASON) or not episode:
        return None
    return int(episode)


def fetch_season_episodes() -> list[dict]:
    _, items = _fetch_channel_and_items()
    episodes = []
    for item in items:
        ep_type = item.findtext("itunes:episodeType", namespaces=NS)
        if ep_type != "full":
            continue
        episode_num = _episode_number_for_item(item)
        if episode_num is None:
            continue
        enclosure = item.find("enclosure")
        episodes.append(
            {
                "episode": episode_num,
                "title": item.findtext("title"),
                "audio_url": enclosure.get("url"),
                "approx_size": int(enclosure.get("length") or 0),
            }
        )
    episodes.sort(key=lambda e: e["episode"])
    return episodes


ESTIMATED_BYTES_PER_SEC = 16 * 1024  # ~128kbps -- what our own encode step actually produces


def fetch_approx_durations(episodes: list[dict]):
    """Fill in approx_duration (seconds) from itunes:duration for planning.

    Also backfills approx_size for any episode whose feed-reported
    enclosure length was 0 (some hosts, e.g. tracking-redirect URLs,
    never populate a real size) -- estimated at the bitrate our own
    encode step actually produces, which is what matters for planning
    since we re-encode everything regardless of source bitrate.
    """
    _, items = _fetch_channel_and_items()
    by_ep = {}
    for item in items:
        episode_num = _episode_number_for_item(item)
        if episode_num is None:
            continue
        d = item.findtext("itunes:duration", namespaces=NS)
        if not d:
            continue
        parts = [int(x) for x in d.split(":")]
        if len(parts) == 3:
            h, m, s = parts
        elif len(parts) == 2:
            h, m, s = 0, *parts
        else:
            h, m, s = 0, 0, parts[0]
        by_ep[episode_num] = h * 3600 + m * 60 + s
    for ep in episodes:
        ep["approx_duration"] = by_ep.get(ep["episode"], 0)
        if not ep["approx_size"]:
            ep["approx_size"] = ep["approx_duration"] * ESTIMATED_BYTES_PER_SEC


# --------------------------------------------------------------------------
# Local audio processing
# --------------------------------------------------------------------------

AAC_ENCODER = "aac"  # overwritten by require_ffmpeg() if aac_at (hardware) is available


def require_ffmpeg():
    global AAC_ENCODER
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg/ffprobe not found on PATH. Install with: brew install ffmpeg")
    # aac_at wraps macOS's AudioToolbox (hardware-accelerated on Apple
    # Silicon) -- measured ~2.2x faster than ffmpeg's software aac
    # encoder for the same output, verified for correct duration/audio.
    # Falls back to plain aac on platforms without it.
    encoders = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True).stdout
    if "aac_at" in encoders:
        AAC_ENCODER = "aac_at"


def ffprobe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _download_progress_hook(label: str):
    last_shown = -1

    def hook(block_count: int, block_size: int, total_size: int):
        nonlocal last_shown
        if total_size <= 0:
            return
        pct = min(100, block_count * block_size * 100 // total_size)
        if pct != last_shown and pct % 10 == 0:
            mb = block_count * block_size / 1024 / 1024
            total_mb = total_size / 1024 / 1024
            print(f"    {label}: downloading... {pct}% ({mb:.0f}/{total_mb:.0f}MB)", end="\r", flush=True)
            last_shown = pct

    return hook


_FFMPEG_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")


def _run_ffmpeg_with_progress(cmd: list[str], total_duration: float, label: str, step: str):
    """Run an ffmpeg command, printing periodic progress parsed from its
    stderr `time=` lines instead of blocking silently for a minute-plus."""
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1)
    last_shown = -1
    stderr_lines = []
    for line in proc.stderr:
        stderr_lines.append(line)
        m = _FFMPEG_TIME_RE.search(line)
        if m and total_duration > 0:
            h, mnt, s = m.groups()
            elapsed = int(h) * 3600 + int(mnt) * 60 + float(s)
            pct = min(100, int(elapsed / total_duration * 100))
            if pct != last_shown and pct % 10 == 0:
                print(f"    {label}: {step}... {pct}%", end="\r", flush=True)
                last_shown = pct
    proc.wait()
    print(" " * 60, end="\r")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output="".join(stderr_lines))


def fetch_raw(url: str, dest: str, label: str = ""):
    """Download url to dest verbatim, no encoding. No-op if dest already
    exists -- callers that need a genuinely fresh copy (e.g. ad_strip's
    two independent downloads of the same URL) must pass a dest that
    doesn't exist yet."""
    if os.path.exists(dest):
        return
    tmp = dest + ".download-tmp"
    urllib.request.urlretrieve(url, tmp, reporthook=_download_progress_hook(label))
    print(" " * 60, end="\r")
    os.rename(tmp, dest)


def fetch_raw_with_headers(url: str, dest: str, label: str = ""):
    """Like fetch_raw, but also returns the HTTP response headers from
    the download (urlretrieve already captures these; fetch_raw just
    doesn't expose them) -- needed for strip_ads: megaphone-header,
    where the ad-break locations come from a response header on this
    same download, not a second request. Returns None (doing nothing
    else) if dest already exists, since there's no download to read
    headers from in that case."""
    if os.path.exists(dest):
        return None
    tmp = dest + ".download-tmp"
    _, headers = urllib.request.urlretrieve(url, tmp, reporthook=_download_progress_hook(label))
    print(" " * 60, end="\r")
    os.rename(tmp, dest)
    return headers


def encode_to_m4a(src: str, dest: str, label: str = ""):
    """Re-encode src (any ffmpeg-readable local audio file) to AAC/M4A at
    dest. No-op if dest already exists.

    Source mp3s often carry an embedded cover-art image as a second
    (video) stream alongside the audio, and Yoto's own MP3 ingest
    pipeline turned out to be unreliable for us regardless of how
    carefully the mp3 was re-encoded (VBR headers, ID3 size, etc. all
    checked out fine locally, but standalone-upload tests through the
    official Yoto app still played a few seconds then cut off/crashed).
    Confirmed via direct A/B test that the same audio re-encoded as
    M4A/AAC uploads and plays correctly, so we convert straight to M4A
    here rather than staying on MP3 at all.
    """
    if os.path.exists(dest):
        return
    base_no_ext, _ = os.path.splitext(dest)
    encoding_tmp = base_no_ext + ".encode-tmp"
    raw_duration = ffprobe_duration(src)
    _run_ffmpeg_with_progress(
        ["ffmpeg", "-y", "-i", src, "-map", "0:a:0", "-c:a", AAC_ENCODER, "-b:a", "128k", "-vn", "-f", "mp4", encoding_tmp],
        raw_duration, label, "encoding",
    )
    os.rename(encoding_tmp, dest)


def download(url: str, dest: str, label: str = ""):
    """One-shot fetch + encode + clean up the raw copy. No-op if dest
    already exists."""
    if os.path.exists(dest):
        return
    base_no_ext, _ = os.path.splitext(dest)
    raw_tmp = base_no_ext + ".download-tmp-raw"
    fetch_raw(url, raw_tmp, label)
    encode_to_m4a(raw_tmp, dest, label)
    os.remove(raw_tmp)


def download_with_dynamic_ad_strip(url: str, dest: str, label: str = ""):
    """strip_ads: dynamic -- for shows served through Megaphone's dynamic
    ad insertion. Fetches TWO independent copies of the same episode,
    diffs them (ad_strip.py) to find ad breaks unique to one copy, and
    encodes the ad-stripped result to dest. Falls back to a plain,
    unmodified encode of copy A if the two downloads don't align
    confidently enough to trust a cut. No-op if dest already exists."""
    if os.path.exists(dest):
        return
    base_no_ext, _ = os.path.splitext(dest)
    raw_a = base_no_ext + ".dlA-tmp"
    raw_b = base_no_ext + ".dlB-tmp"
    fetch_raw(url, raw_a, label=f"{label} (copy A)")
    fetch_raw(url, raw_b, label=f"{label} (copy B)")
    duration_a = ffprobe_duration(raw_a)

    try:
        cuts = ad_strip.find_cut_ranges(raw_a, raw_b, duration_a)
    except ad_strip.AlignmentTooUncertain as exc:
        print(f"    {label}: ad-strip alignment uncertain ({exc}); keeping full audio, unedited")
        cuts = []

    if cuts:
        total = sum(e - s for s, e in cuts)
        print(f"    {label}: found {len(cuts)} ad break(s) totaling {total:.0f}s -- removing")

    encoding_tmp = base_no_ext + ".encode-tmp"
    ad_strip.encode_with_cuts(raw_a, cuts, duration_a, encoding_tmp, AAC_ENCODER, label=label)
    os.remove(raw_a)
    os.remove(raw_b)
    os.rename(encoding_tmp, dest)


def download_with_megaphone_header_strip(url: str, dest: str, label: str = ""):
    """strip_ads: megaphone-header -- for shows served through Megaphone,
    which sends an exact byte-offset map of every pre/mid/post-roll ad
    segment in the x-megaphone-payload-2 response header on every
    single download (see ad_strip.py's megaphone-header section for the
    full story on how this was found and the header format). Needs only
    ONE download -- no diffing, no fingerprinting -- and is byte-precise
    rather than probabilistic, so prefer this over 'dynamic'/'leading'
    for any show confirmed to send the header. Falls back to a plain,
    unedited encode if the header is missing or has nothing to cut. No-
    op if dest already exists."""
    if os.path.exists(dest):
        return
    base_no_ext, _ = os.path.splitext(dest)
    raw_tmp = base_no_ext + ".download-tmp-raw"
    headers = fetch_raw_with_headers(url, raw_tmp, label)
    duration = ffprobe_duration(raw_tmp)

    cuts = []
    payload2 = headers.get("x-megaphone-payload-2") if headers else None
    if payload2:
        cuts = ad_strip.parse_megaphone_cut_ranges(payload2, os.path.getsize(raw_tmp), duration)
    else:
        print(f"    {label}: no Megaphone ad-break header on this download; keeping full audio, unedited")

    if cuts:
        total = sum(e - s for s, e in cuts)
        print(f"    {label}: found {len(cuts)} Megaphone-labeled ad segment(s) totaling {total:.0f}s -- removing")
        encoding_tmp = base_no_ext + ".encode-tmp"
        ad_strip.encode_with_cuts(raw_tmp, cuts, duration, encoding_tmp, AAC_ENCODER, label=label)
        os.rename(encoding_tmp, dest)
    else:
        encode_to_m4a(raw_tmp, dest, label)
    os.remove(raw_tmp)


# Populated once per run by prepare_leader_template(), for strip_ads: leading.
LEADER_TEMPLATE: list[tuple] | None = None
_LEADER_TEMPLATE_ATTEMPTED = False


def fetch_head_clip(url: str, dest: str, seconds: float, label: str = ""):
    """Fetch just the first `seconds` of url, encoded straight to dest --
    streams+trims+encodes in one ffmpeg pass, so this is much cheaper
    than a full download for shows where only the opening matters (see
    prepare_leader_template). No-op if dest already exists."""
    if os.path.exists(dest):
        return
    tmp = dest + ".download-tmp"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-headers", "User-Agent: yoto-custom-podcast-uploader/1.0\r\n",
        "-i", url, "-t", str(seconds), "-c:a", AAC_ENCODER, "-b:a", "128k", "-vn", "-f", "mp4", tmp,
    ]
    print(f"    {label}: fetching head clip...")
    subprocess.run(cmd, capture_output=True, check=True)
    os.rename(tmp, dest)


def prepare_leader_template(episodes: list[dict]):
    """strip_ads: leading setup, called once per run before the main
    per-card loop: fetches short head clips of two reference episodes
    (first and last in the season -- arbitrary but maximally different,
    so if the derived span is real content, it isn't real content) and
    derives the show's recurring leader/jingle from what they share
    (ad_strip.derive_leader_template). Stores the result in the module-
    level LEADER_TEMPLATE for download_with_leading_ad_strip to use for
    every episode. Leaves LEADER_TEMPLATE as None (logging why) if no
    confident common span is found -- callers must treat that as "can't
    strip ads for this podcast run", not an error."""
    global LEADER_TEMPLATE, _LEADER_TEMPLATE_ATTEMPTED
    if _LEADER_TEMPLATE_ATTEMPTED:
        return
    _LEADER_TEMPLATE_ATTEMPTED = True

    if len(episodes) < 2:
        print("  strip_ads: leading needs at least 2 episodes to derive a leader template; skipping ad-strip.")
        return

    os.makedirs(WORK_DIR, exist_ok=True)
    ref_a, ref_b = episodes[0], episodes[-1]
    path_a = os.path.join(WORK_DIR, "_leader_ref_a.m4a")
    path_b = os.path.join(WORK_DIR, "_leader_ref_b.m4a")
    print(f"  Deriving leader template from episodes {ref_a['episode']} and {ref_b['episode']}...")
    fetch_head_clip(ref_a["audio_url"], path_a, ad_strip.HEAD_WINDOW_S, label=f"leader ref (ep {ref_a['episode']})")
    fetch_head_clip(ref_b["audio_url"], path_b, ad_strip.HEAD_WINDOW_S, label=f"leader ref (ep {ref_b['episode']})")

    LEADER_TEMPLATE = ad_strip.derive_leader_template([path_a, path_b])
    if LEADER_TEMPLATE is None:
        print("  strip_ads: leading found no confident common leader between the reference episodes; "
              "episodes will be left unedited.")
    else:
        print(f"  Leader template: {len(LEADER_TEMPLATE) * ad_strip.HOP_S:.1f}s")


def download_with_leading_ad_strip(url: str, dest: str, label: str = ""):
    """strip_ads: leading -- for shows with a static (non-dynamic) ad
    slot before a consistent intro jingle. Downloads the episode once,
    finds where LEADER_TEMPLATE (see prepare_leader_template) starts in
    its opening minutes, and cuts everything before that. Falls back to
    a plain, unmodified encode if no template is available or no
    confident match is found. No-op if dest already exists."""
    if os.path.exists(dest):
        return
    base_no_ext, _ = os.path.splitext(dest)
    raw_tmp = base_no_ext + ".download-tmp-raw"
    fetch_raw(url, raw_tmp, label)
    encoding_tmp = base_no_ext + ".encode-tmp"

    cut_point = ad_strip.find_leader_cut(raw_tmp, LEADER_TEMPLATE) if LEADER_TEMPLATE else None
    if cut_point is None or cut_point < ad_strip.MIN_CUT_S:
        encode_to_m4a(raw_tmp, dest, label)
    else:
        print(f"    {label}: leader starts at {cut_point:.1f}s -- removing everything before it")
        duration = ffprobe_duration(raw_tmp)
        ad_strip.encode_with_cuts(raw_tmp, [(0.0, cut_point)], duration, encoding_tmp, AAC_ENCODER, label=label)
        os.rename(encoding_tmp, dest)
    os.remove(raw_tmp)


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


def split_audio(path: str, split_at: float, out_a: str, out_b: str, duration: float, label: str = ""):
    if os.path.exists(out_a) and os.path.exists(out_b):
        return
    _run_ffmpeg_with_progress(
        ["ffmpeg", "-y", "-i", path, "-to", f"{split_at}", "-c:a", AAC_ENCODER, "-b:a", "128k", "-f", "mp4", out_a],
        split_at, label, "splitting (part 1)",
    )
    _run_ffmpeg_with_progress(
        ["ffmpeg", "-y", "-i", path, "-ss", f"{split_at}", "-c:a", AAC_ENCODER, "-b:a", "128k", "-f", "mp4", out_b],
        duration - split_at, label, "splitting (part 2)",
    )


def prepare_episode_tracks(ep: dict) -> list[dict]:
    """Download an episode and return 1-2 local track dicts (title, path, part)."""
    os.makedirs(WORK_DIR, exist_ok=True)
    base = f"ep{ep['episode']:02d}"
    label = f"Episode {ep['episode']}"
    raw_path = os.path.join(WORK_DIR, base + ".m4a")
    if STRIP_ADS == "megaphone-header":
        download_with_megaphone_header_strip(ep["audio_url"], raw_path, label=label)
    elif STRIP_ADS == "dynamic":
        download_with_dynamic_ad_strip(ep["audio_url"], raw_path, label=label)
    elif STRIP_ADS == "leading":
        download_with_leading_ad_strip(ep["audio_url"], raw_path, label=label)
    else:
        download(ep["audio_url"], raw_path, label=label)
    duration = ffprobe_duration(raw_path)

    if duration <= SPLIT_THRESHOLD_SEC:
        return [{"title": ep["title"], "path": raw_path, "duration": duration, "part": None}]

    split_at = find_split_point(raw_path, duration)
    part_a = os.path.join(WORK_DIR, base + "a.m4a")
    part_b = os.path.join(WORK_DIR, base + "b.m4a")
    split_audio(raw_path, split_at, part_a, part_b, duration, label=label)
    dur_a = ffprobe_duration(part_a)
    dur_b = ffprobe_duration(part_b)
    return [
        {"title": f"{ep['title']} (Part 1)", "path": part_a, "duration": dur_a, "part": 1},
        {"title": f"{ep['title']} (Part 2)", "path": part_b, "duration": dur_b, "part": 2},
    ]


# --------------------------------------------------------------------------
# Icons
# --------------------------------------------------------------------------

def prepare_icon(card_index: int, episode_num: int, part: int | None) -> str:
    os.makedirs(ICON_DIR, exist_ok=True)
    suffix = f"_p{part}" if part else ""
    path = os.path.join(ICON_DIR, f"c{card_index:02d}_e{episode_num:02d}{suffix}.png")
    if not os.path.exists(path):
        save_icon(SEASON, card_index, episode_num, path, part=part, palette=ICON_PALETTE)
    return path


def prepare_base_cover_image(source_url: str) -> str:
    """Download the podcast's own cover art once, cached locally."""
    os.makedirs(WORK_DIR, exist_ok=True)
    path = os.path.join(WORK_DIR, "cover_base.png")
    if not os.path.exists(path):
        downloading_tmp = os.path.join(WORK_DIR, "cover_base.download-tmp")
        urllib.request.urlretrieve(source_url, downloading_tmp)
        Image.open(downloading_tmp).convert("RGB").save(path, "PNG")
        os.remove(downloading_tmp)
    return path


def prepare_card_cover(card_index: int, base_cover_path: str) -> str:
    """Composite this card's S<season>.<card> badge onto a copy of the
    base cover art. Padded to a portrait shape first (see
    icon_gen.pad_to_safe_portrait) so the app's own crop for its card-list
    display -- confirmed to trim left/right, keeping full height -- can't
    cut into the real art; the badge (icon_gen.apply_cover_badge) then
    goes near the top of that padded canvas."""
    os.makedirs(WORK_DIR, exist_ok=True)
    path = os.path.join(WORK_DIR, f"cover_card{card_index:02d}.png")
    if not os.path.exists(path):
        base = Image.open(base_cover_path)
        padded = pad_to_safe_portrait(base)
        badged = apply_cover_badge(padded, SEASON, card_index, palette=ICON_PALETTE)
        badged.convert("RGB").save(path, "PNG")
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


# --------------------------------------------------------------------------
# Manifest (idempotency across re-runs)
# --------------------------------------------------------------------------

def load_manifest() -> dict:
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
        manifest.setdefault("icons", {})
        manifest.setdefault("cover_urls", {})
        return manifest
    return {"episodes": {}, "cards": {}, "icons": {}, "cover_urls": {}}


def save_manifest(manifest: dict):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


# --------------------------------------------------------------------------
# Upload + card creation
# --------------------------------------------------------------------------

def upload_track(client: YotoClient, local_track: dict, card_index: int, episode_num: int, manifest: dict) -> dict:
    # Icon prep/upload is independent of the audio cache below -- it has
    # its own cache (manifest["icons"], keyed by icon filename) so an icon
    # redesign can be picked up on a re-run without needing to re-upload
    # already-cached audio too.
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
        line = f"    {local_track['title']}: {msg}"
        print(line.ljust(90), end="\r", flush=True)

    info = client.upload_audio(local_track["path"], on_progress=progress)
    print(" " * 90, end="\r")

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
    config = load_podcasts_config()

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--podcast", choices=sorted(config.keys()),
                         help="Which podcast from podcasts.yaml to build.")
    parser.add_argument("--season", type=int, help="Which season number to build (e.g. 1).")
    parser.add_argument("--list-podcasts", action="store_true",
                         help="List configured podcasts from podcasts.yaml and exit.")
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

    if args.list_podcasts:
        for name, entry in sorted(config.items()):
            seasons = sorted(entry.get("local_feed_paths", {}).keys()) or ["(any)"]
            print(f"  {name:10s} {entry['title']!r} -- configured seasons: {seasons}")
        return

    if not args.podcast:
        parser.error("--podcast is required (see --list-podcasts for options)")
    if not args.season:
        parser.error("--season is required, e.g. --season 1")

    configure_for_podcast(args.podcast, args.season, config)

    episodes = fetch_season_episodes()
    fetch_approx_durations(episodes)
    print(f"Found {len(episodes)} Season {SEASON} full episodes.")

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
    if STRIP_ADS == "leading":
        prepare_leader_template(episodes)
    manifest = load_manifest()
    token = get_access_token(force_login=args.force_login)
    client = YotoClient(token)

    base_cover_path = None
    source_image_url = fetch_channel_image_url()
    if source_image_url:
        print(f"Fetching podcast cover art from {source_image_url} ...")
        base_cover_path = prepare_base_cover_image(source_image_url)

    manifest.setdefault("cover_urls", {})

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

        cover_url = manifest["cover_urls"].get(card_key)
        if not cover_url and base_cover_path:
            print(f"  Uploading cover art badged 'S{SEASON}.{i}'...")
            card_cover_path = prepare_card_cover(i, base_cover_path)
            cover_url = client.upload_cover_image_file(card_cover_path)
            manifest["cover_urls"][card_key] = cover_url
            save_manifest(manifest)

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
