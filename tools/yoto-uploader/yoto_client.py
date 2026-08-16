"""
Thin wrapper around the bits of the Yoto API this tool needs:
audio upload + transcode, and card (content) creation.

Docs: https://yoto.dev/api/

Set YOTO_DEBUG=1 to print raw request/response bodies for every call --
useful for confirming/fixing the exact response shapes, since some of
these were implemented from documentation summaries rather than a live
account.
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
                headers={"Content-Type": "audio/mpeg"},
            )
            put_resp.raise_for_status()
            if on_progress:
                on_progress("uploaded, transcoding...")
        else:
            if on_progress:
                on_progress("already on Yoto's servers (dedup by checksum)")

        last_body = None
        for attempt in range(180):
            poll = self.session.get(
                f"{API_BASE}/media/upload/{upload_id}/transcoded",
                params={"loudnorm": "false"},
                headers={"Accept": "application/json"},
            )
            poll.raise_for_status()
            body = poll.json()
            last_body = body
            if attempt == 0 or DEBUG:
                _debug(f"transcode poll #{attempt}", body)
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
            if on_progress and attempt % 10 == 0 and attempt > 0:
                on_progress(f"still transcoding... ({attempt}s)")
            time.sleep(1)

        raise TimeoutError(
            f"Transcoding did not finish for {file_path}.\n"
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
