"""Calls to psd-agents, the incident workflow: candidate delivery and the coordinator routes.

On Cloud Run psd-agents accepts only callers with a Google-signed ID token for its URL, so every https call carries
one, fetched for psd-api's own service account. A local workflow on http://127.0.0.1 needs none.
"""

import os
import threading
import time
from typing import Any

import google.auth.transport.requests
import httpx
from google.oauth2 import id_token

URL = os.environ.get("PSD_AGENTS_URL", "http://127.0.0.1:8000").rstrip("/")
# Google ID tokens last an hour; one is reused until ten minutes before that.
TOKEN_SECONDS = 50 * 60

_token: dict[str, Any] = {"value": None, "at": 0.0}
_token_lock = threading.Lock()


def _headers() -> dict[str, str]:
    if not URL.startswith("https://"):
        return {}
    with _token_lock:
        if not _token["value"] or time.monotonic() - _token["at"] > TOKEN_SECONDS:
            _token["value"] = id_token.fetch_id_token(
                google.auth.transport.requests.Request(), URL
            )
            _token["at"] = time.monotonic()
        return {"Authorization": f"Bearer {_token['value']}"}


def call(
    method: str, path: str, json: Any = None, timeout: float = 60
) -> httpx.Response:
    return httpx.request(
        method, f"{URL}{path}", json=json, headers=_headers(), timeout=timeout
    )
