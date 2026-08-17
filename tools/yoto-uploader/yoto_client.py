"""
Thin wrapper around the bits of the Yoto API this tool needs:
audio upload + transcode, and card (content) creation.

Docs: https://yoto.dev/api/ (incomplete in places -- the required
`sha256` param on the upload-URL request, the nested `transcodedInfo`
shape of the transcode poll response, and the icon-upload endpoint were
confirmed by reading the working implementation in
https://github.com/xkjq/yoto-up (MIT licensed), credit to its author.

Set YOTO_DEBUG=1 to print raw request/response bodies for every call.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import requests

API_BASE = "https://api.yotoplay.com"
DEBUG = os.environ.get("YOTO_DEBUG") == "1"


def _debug(label: str, obj):
    if DEBUG:
        print(f"    [debug] {label}: {json.dumps(obj, indent=2)[:2000]}")


class YotoClient:
    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token}"

    def upload_audio(self, file_path: str, on_progress=None) -> dict:
        """Upload a local audio file and wait for transcoding to finish.

        Returns a flat dict: transcodedSha256, format, duration, fileSize,
        channels.
        """
        with open(file_path, "rb") as f:
            data = f.read()
        sha256 = hashlib.sha256(data).hexdigest()

        resp = self.session.get(
            f"{API_BASE}/media/transcode/audio/uploadUrl",
            params={"sha256": sha256},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        resp_body = resp.json()
        _debug("uploadUrl response", resp_body)
        upload = resp_body["upload"] if "upload" in resp_body else resp_body
        upload_url = upload["uploadUrl"]
        upload_id = upload["uploadId"]

        if upload_url:
            put_resp = requests.put(
                upload_url,
                data=data,
                headers={"Content-Type": "audio/mp4"},
            )
            put_resp.raise_for_status()
            if on_progress:
                on_progress("uploaded, waiting for status...")
        else:
            if on_progress:
                on_progress("already on Yoto's servers (dedup by checksum)")

        # Poll until done, bailing out only if progress stalls (not just on
        # a fixed attempt count) -- larger/slower files can take several
        # minutes, and the API reports a real progress.percent we can watch.
        last_body = None
        last_percent = -1
        last_phase = "processing"
        stalled_for = 0
        max_stall_seconds = 180  # give up only if no progress for this long
        max_total_seconds = 20 * 60
        elapsed = 0

        while elapsed < max_total_seconds:
            poll = self.session.get(
                f"{API_BASE}/media/upload/{upload_id}/transcoded",
                params={"loudnorm": "false"},
                headers={"Accept": "application/json"},
            )
            poll.raise_for_status()
            body = poll.json()
            last_body = body
            if elapsed == 0 or DEBUG:
                _debug(f"transcode poll @{elapsed}s", body)
            transcode = body.get("transcode") or body
            if transcode.get("transcodedSha256"):
                info = transcode.get("transcodedInfo") or {}
                return {
                    "transcodedSha256": transcode["transcodedSha256"],
                    "format": info.get("format"),
                    "duration": info.get("duration"),
                    "fileSize": info.get("fileSize"),
                    "channels": info.get("channels"),
                }

            progress_info = transcode.get("progress") or {}
            percent = progress_info.get("percent")
            phase = progress_info.get("phase") or "processing"
            last_phase = phase
            if percent is not None and percent != last_percent:
                stalled_for = 0
                last_percent = percent
                if on_progress:
                    on_progress(f"{phase}... {percent}%")
            else:
                stalled_for += 2
                if stalled_for >= max_stall_seconds:
                    raise TimeoutError(
                        f"{last_phase} stalled at {last_percent}% for {file_path} "
                        f"(no progress for {max_stall_seconds}s).\n"
                        f"Last poll response: {json.dumps(last_body, indent=2)}\n"
                        f"Re-run with YOTO_DEBUG=1 for the full request/response trail."
                    )

            time.sleep(2)
            elapsed += 2

        raise TimeoutError(
            f"{last_phase} did not finish for {file_path} within {max_total_seconds}s.\n"
            f"Last poll response: {json.dumps(last_body, indent=2)}\n"
            f"Re-run with YOTO_DEBUG=1 for the full request/response trail."
        )

    def create_or_update_content(self, content: dict) -> dict:
        _debug("createOrUpdateContent request", content)
        resp = self.session.post(f"{API_BASE}/content", json=content)
        if not resp.ok:
            _debug(f"createOrUpdateContent error {resp.status_code}", resp.text[:2000])
        resp.raise_for_status()
        body = resp.json()
        _debug("createOrUpdateContent response", body)
        return body

    def upload_icon(self, png_path: str, filename: str) -> str:
        """Upload a 16x16 PNG icon. Returns the mediaId to reference as
        `yoto:#{mediaId}` in a chapter/track's display.icon16x16."""
        with open(png_path, "rb") as f:
            data = f.read()
        resp = self.session.post(
            f"{API_BASE}/media/displayIcons/user/me/upload",
            params={"autoConvert": "true", "filename": filename},
            headers={"Content-Type": "image/png"},
            data=data,
        )
        resp.raise_for_status()
        body = resp.json()
        _debug("upload_icon response", body)
        icon = body.get("displayIcon", body)
        return icon["mediaId"]

    def upload_cover_image(self, image_url: str) -> str:
        """Have Yoto fetch and host a cover image from a URL. Returns the
        mediaUrl to set as a card's metadata.cover.imageL."""
        resp = self.session.post(
            f"{API_BASE}/media/coverImage/user/me/upload",
            params={"imageUrl": image_url, "autoconvert": "true"},
        )
        resp.raise_for_status()
        body = resp.json()
        _debug("upload_cover_image response", body)
        cover = body.get("coverImage", body)
        return cover.get("mediaUrl") or cover.get("media_url")

    def upload_cover_image_file(self, png_path: str) -> str:
        """Upload a local cover image file's bytes directly (for a
        per-card composited cover, as opposed to fetching a shared URL
        server-side). Returns the mediaUrl for metadata.cover.imageL."""
        with open(png_path, "rb") as f:
            data = f.read()
        resp = self.session.post(
            f"{API_BASE}/media/coverImage/user/me/upload",
            params={"autoconvert": "true"},
            headers={"Content-Type": "image/png"},
            data=data,
        )
        resp.raise_for_status()
        body = resp.json()
        _debug("upload_cover_image_file response", body)
        cover = body.get("coverImage", body)
        return cover.get("mediaUrl") or cover.get("media_url")
