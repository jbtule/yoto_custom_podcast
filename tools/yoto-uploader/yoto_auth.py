"""
PKCE login + token cache for the Yoto API.

Nothing here ever touches git: the token cache lives in
tools/yoto-uploader/.state/credentials.json, which is gitignored.

Usage:
    from yoto_auth import get_access_token
    token = get_access_token()   # opens a browser the first time, silent after
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser

import requests

AUTH_BASE = "https://login.yotoplay.com"
API_AUDIENCE = "https://api.yotoplay.com"
REDIRECT_URI = "http://127.0.0.1:8787/callback"
SCOPES = "offline_access user:content:manage"

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".state")
CREDENTIALS_PATH = os.path.join(STATE_DIR, "credentials.json")


def _client_id() -> str:
    client_id = os.environ.get("YOTO_CLIENT_ID")
    if not client_id:
        raise SystemExit(
            "YOTO_CLIENT_ID is not set.\n"
            "Register a public app at https://dashboard.yoto.dev/ with redirect URI\n"
            f"  {REDIRECT_URI}\n"
            "then run:\n"
            "  export YOTO_CLIENT_ID=<your client id>\n"
        )
    return client_id


def _load_cached() -> dict | None:
    if os.path.exists(CREDENTIALS_PATH):
        with open(CREDENTIALS_PATH) as f:
            return json.load(f)
    return None


def _save_cached(tokens: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CREDENTIALS_PATH, "w") as f:
        json.dump(tokens, f, indent=2)
    os.chmod(CREDENTIALS_PATH, 0o600)


def _refresh(client_id: str, refresh_token: str) -> dict | None:
    resp = requests.post(
        f"{AUTH_BASE}/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
    )
    if resp.status_code != 200:
        return None
    tokens = resp.json()
    tokens.setdefault("refresh_token", refresh_token)
    tokens["obtained_at"] = time.time()
    return tokens


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        self.server.auth_code = params.get("code", [None])[0]
        self.server.auth_error = params.get("error_description", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = "You can close this tab and go back to the terminal."
        if self.server.auth_error:
            msg = f"Login failed: {self.server.auth_error}"
        self.wfile.write(f"<html><body><p>{msg}</p></body></html>".encode())

    def log_message(self, *args):  # silence default request logging
        pass


def _login_via_browser(client_id: str) -> dict:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )

    server = http.server.HTTPServer(("127.0.0.1", 8787), _CallbackHandler)
    server.auth_code = None
    server.auth_error = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    query = urllib.parse.urlencode(
        {
            "audience": API_AUDIENCE,
            "scope": SCOPES,
            "response_type": "code",
            "client_id": client_id,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "redirect_uri": REDIRECT_URI,
        }
    )
    url = f"{AUTH_BASE}/authorize?{query}"
    print(f"Opening browser to log in to Yoto:\n  {url}\n")
    webbrowser.open(url)

    print("Waiting for login...")
    deadline = time.time() + 300
    while server.auth_code is None and server.auth_error is None:
        if time.time() > deadline:
            server.shutdown()
            raise SystemExit("Timed out waiting for Yoto login.")
        time.sleep(0.25)
    server.shutdown()

    if server.auth_error:
        raise SystemExit(f"Yoto login failed: {server.auth_error}")

    resp = requests.post(
        f"{AUTH_BASE}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code_verifier": verifier,
            "code": server.auth_code,
            "redirect_uri": REDIRECT_URI,
        },
    )
    resp.raise_for_status()
    tokens = resp.json()
    tokens["obtained_at"] = time.time()
    return tokens


def get_access_token(force_login: bool = False) -> str:
    client_id = _client_id()
    cached = None if force_login else _load_cached()

    if cached:
        age = time.time() - cached.get("obtained_at", 0)
        if age < cached.get("expires_in", 0) - 60:
            return cached["access_token"]
        refreshed = _refresh(client_id, cached.get("refresh_token", ""))
        if refreshed:
            _save_cached(refreshed)
            return refreshed["access_token"]
        print("Cached Yoto session expired and could not be refreshed; logging in again.")

    tokens = _login_via_browser(client_id)
    _save_cached(tokens)
    return tokens["access_token"]
