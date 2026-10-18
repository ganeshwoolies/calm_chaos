"""Store links: a store's page opens with a token signed for that store, so a link acts for one store and no other.

The token is an HMAC of the store id under PSD_STORE_TOKEN_SALT (Secret Manager on Cloud Run). The link carries it in
its fragment, which a browser never sends to a server; the page then sends it in the X-Store-Token header. Only the
coordinator page hands links out.
"""

import base64
import hashlib
import hmac
import os


def salt() -> str | None:
    return os.environ.get("PSD_STORE_TOKEN_SALT") or None


def token(store_id: str, key: str) -> str:
    digest = hmac.new(
        key.encode(), f"store:{store_id}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode()


def link(store_id: str) -> str:
    """The store page's address for one store; without a salt (local development) it carries no token."""
    key = salt()
    return f"/store?store={store_id}" + (
        f"#token={token(store_id, key)}" if key else ""
    )


def valid(store_id: str, given: str) -> bool:
    key = salt()
    return bool(key and store_id and given) and hmac.compare_digest(
        given.encode(), token(store_id, key).encode()
    )
