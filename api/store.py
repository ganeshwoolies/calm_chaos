"""The store page: an associate checks a pack's label and closes their store's tasks with a shelf photo. Served by
psd-api beside the desk.

The page is public. Every API call acts for one store, named by the X-Store-Id header and proved by the store link's
token (api/storelinks.py), so a call sees only that store's tasks, a photo for another store's task is refused, and
the desk passcode opens nothing here. A task is closed only by a shelf photo (api/shelves.py). Without
PSD_STORE_TOKEN_SALT (local development) only loopback callers are served.
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api import desk, identity, labels, shelves, storelinks

PAGE = Path(__file__).parent / "static" / "store.html"
LOOPBACK = ("127.0.0.1", "::1", "localhost")
# What a store sees of a task: no draft text, customer message or other store.
TASK_FIELDS = (
    "task_id",
    "kind",
    "code",
    "aisle",
    "qty_on_hand",
    "status",
    "due_at",
    "note",
)


def _store(request: Request) -> str:
    """The store this request acts for, once its link is proved."""
    store_id = request.headers.get("x-store-id", "")
    if storelinks.salt():
        if not storelinks.valid(store_id, request.headers.get("x-store-token", "")):
            raise HTTPException(
                status_code=401,
                detail="Open this page from the store link the coordinator gave you.",
            )
    else:
        host = request.client.host if request.client else ""
        if host not in LOOPBACK:
            raise HTTPException(
                status_code=403,
                detail="Set PSD_STORE_TOKEN_SALT to serve store pages to other hosts.",
            )
    if store_id not in {s["store_id"] for s in labels.stores()}:
        raise HTTPException(status_code=404, detail=f"No store {store_id}")
    return store_id


router = APIRouter()
api = APIRouter(prefix="/store/api")


class LabelPhoto(BaseModel):
    image_base64: str
    mime_type: str = "image/jpeg"


class ProductPick(BaseModel):
    product_id: str


class ShelfPhoto(BaseModel):
    image_base64: str
    mime_type: str = "image/jpeg"


@router.get("/store", include_in_schema=False)
def page() -> FileResponse:
    # Revalidated on every open, so a deploy never leaves a browser on the old page.
    return FileResponse(
        PAGE, media_type="text/html", headers={"Cache-Control": "no-cache"}
    )


def tasks_of(store_id: str) -> list[dict[str, Any]]:
    """This store's tasks across every incident, with only the incident's title, severity and kind."""
    out = []
    for i in desk._agents("GET", "/desk/incidents"):
        for t in i.get("tasks") or []:
            if t.get("store_id") != store_id:
                continue
            out.append(
                {
                    **{k: t.get(k) for k in TASK_FIELDS},
                    "incident": {
                        "incident_id": i.get("incident_id"),
                        "title": i.get("title"),
                        "severity": i.get("severity"),
                        "kind": i.get("kind"),
                        "product_id": i.get("product_id"),
                        "product_name": i.get("product_name"),
                    },
                }
            )
    return out


@api.get("/me")
def me(store_id: str = Depends(_store)) -> dict[str, Any]:
    return next(s for s in labels.stores() if s["store_id"] == store_id)


@api.get("/tasks")
def tasks(store_id: str = Depends(_store)) -> list[dict[str, Any]]:
    return tasks_of(store_id)


@api.post("/firebase-token")
def firebase_token(store_id: str = Depends(_store)) -> dict[str, str]:
    """The proved store link, exchanged for a Firebase custom token that lets the page listen to its own tasks."""
    try:
        return {"token": identity.store_token(store_id)}
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Store sign-in is unavailable: {e}"
        ) from e


@api.post("/tasks/{task_id}/photo")
def shelf_photo(
    task_id: str, body: ShelfPhoto, store_id: str = Depends(_store)
) -> dict[str, Any]:
    task = next((t for t in tasks_of(store_id) if t["task_id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail=f"No task {task_id} at {store_id}")
    try:
        result = shelves.check(task, body.image_base64, body.mime_type)
    except shelves.ShelfError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    return {**result, "tasks": tasks_of(store_id)}


@api.post("/labels")
def label_check(body: LabelPhoto, store_id: str = Depends(_store)) -> dict[str, Any]:
    try:
        return labels.check(store_id, body.image_base64, body.mime_type)
    except labels.LabelError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@api.post("/labels/{check_id}/product")
def pick_product(
    check_id: str, body: ProductPick, store_id: str = Depends(_store)
) -> dict[str, Any]:
    try:
        return labels.choose(check_id, body.product_id, store_id)
    except labels.LabelError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


router.include_router(api)
