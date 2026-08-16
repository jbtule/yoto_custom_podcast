"""
Thin wrapper around the bits of the Yoto API this tool needs:
audio upload + transcode, and card (content) creation.

Docs: https://yoto.dev/api/
"""
from __future__ import annotations

import time

import requests

API_BASE = "https://api.yotoplay.com"


class YotoClient:
    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token}"

    def upload_audio(self, file_path: str, on_progress=None) -> dict:
        """Upload a local audio file and wait for transcoding to finish.

        Returns the `transcodedInfo` dict (format, duration, fileSize,
        channels, transcodedSha256, ...).
        """
        resp = self.session.get(
            f"{API_BASE}/media/transcode/audio/uploadUrl",
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        upload = resp.json()["upload"] if "upload" in resp.json() else resp.json()
        upload_url = upload["uploadUrl"]
        upload_id = upload["uploadId"]

        if upload_url:
            with open(file_path, "rb") as f:
                data = f.read()
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

        for _ in range(120):
            poll = self.session.get(
                f"{API_BASE}/media/upload/{upload_id}/transcoded",
                params={"loudnorm": "false"},
                headers={"Accept": "application/json"},
            )
            poll.raise_for_status()
            body = poll.json()
            info = body.get("transcode") or body
            if info.get("transcodedSha256"):
                return info
            time.sleep(1)

        raise TimeoutError(f"Transcoding did not finish for {file_path}")

    def create_or_update_content(self, content: dict) -> dict:
        resp = self.session.post(f"{API_BASE}/content", json=content)
        resp.raise_for_status()
        return resp.json()
