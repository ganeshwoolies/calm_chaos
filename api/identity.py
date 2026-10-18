"""Who is calling, when the desk and store pages are served by Firebase Hosting.

Coordinators sign in with Firebase Authentication (Google, or email and password) and send their Firebase ID token. It
is verified against the project's Firebase signing keys, and only an account carrying the coordinator custom claim
(set by tools/grant_coordinator.py) is a coordinator; its email becomes the actor on every decision and promotion. The
desk passcode keeps working beside it, for the pages psd-api serves itself.

A store page opened from its signed link exchanges the link for a Firebase custom token carrying its store_id. psd-api's
service account mints it through IAM signBlob (it needs roles/iam.serviceAccountTokenCreator on itself), and Firestore's
rules (firestore.rules) then show that page its own store's tasks only.
"""

import os
import threading
import time

import google.auth
from google.auth import exceptions, iam, jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

FIREBASE_TOKEN_AUDIENCE = "https://identitytoolkit.googleapis.com/google.identity.identitytoolkit.v1.IdentityToolkit"
CUSTOM_TOKEN_SECONDS = 3600

# Verified ID tokens until they expire, so a page polling every few seconds does not refetch the signing keys each time.
_verified: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def _project() -> str | None:
    return os.environ.get("GOOGLE_CLOUD_PROJECT")


def coordinator(token: str) -> str | None:
    """The email of a signed-in coordinator, or None when the token is not a valid coordinator's.

    Raises google.auth.exceptions.TransportError when the signing keys cannot be fetched: the token was not checked, so
    it is not refused.
    """
    now = time.time()
    with _lock:
        cached = _verified.get(token)
        if cached and cached[1] > now:
            return cached[0]
    project = _project()
    if not (project and token):
        return None
    try:
        claims = id_token.verify_firebase_token(
            token, google_requests.Request(), audience=project
        )
    except exceptions.TransportError:
        raise
    except (ValueError, exceptions.GoogleAuthError):
        return None
    if not claims or claims.get("coordinator") is not True:
        return None
    actor = str(claims.get("email") or claims.get("sub"))
    with _lock:
        _verified[token] = (actor, float(claims.get("exp", now)))
        for stale in [t for t, (_, exp) in _verified.items() if exp <= now]:
            _verified.pop(stale, None)
    return actor


def store_token(store_id: str) -> str:
    """A Firebase custom token for one store's page, signed by this service's own service account."""
    credentials, _ = google.auth.default()
    request = google_requests.Request()
    if not credentials.valid:
        credentials.refresh(request)
    email = getattr(credentials, "service_account_email", None)
    if not email or email == "default":
        raise RuntimeError(
            "store sign-in needs a service account (Cloud Run), not user credentials"
        )
    now = int(time.time())
    payload = {
        "iss": email,
        "sub": email,
        "aud": FIREBASE_TOKEN_AUDIENCE,
        "iat": now,
        "exp": now + CUSTOM_TOKEN_SECONDS,
        "uid": f"store-{store_id}",
        "claims": {"store_id": store_id},
    }
    token = jwt.encode(iam.Signer(request, credentials, email), payload)
    return token.decode() if isinstance(token, bytes) else token
