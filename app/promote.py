"""Promotion: an observation a coordinator verifies becomes a note in the knowledge bundle, by GitHub pull request.

The note is read from and written to the base branch, not the copy pinned in the image, so two promotions to one note
both land. The pull request touches only knowledge/learned/**, which is what lets it merge without a code owner's
review. While it is open the observation is left out of retrieval (memory.retrieve skips memories whose link carries
promotion_pr). settle() deletes the memory once the merge is deployed, and returns the observation to retrieval when
the pull request is closed without merging.

GitHub is reached with PSD_GITHUB_TOKEN on PSD_GITHUB_REPO (owner/name), against PSD_GITHUB_BASE (default main).
Without a token, promotion is unavailable and says why; listing and deleting observations still work.
"""

import base64
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import yaml

from app import knowledge, learn
from app.knowledge import split_frontmatter
from app.store import LocalStore, now

logger = logging.getLogger(__name__)

API = "https://api.github.com"
LEARNED = "knowledge/learned"
LABEL = "promotion"

# Memory Bank scope key -> (folder under learned/, OKF type, index section).
_SCOPES = {
    "supplier_id": ("suppliers", "Supplier Note", "Suppliers"),
    "product_id": ("products", "Product Note", "Products"),
    "store_id": ("stores", "Store Note", "Stores"),
    "playbook": ("playbook", "Playbook", "Playbook"),
}
# Every coordinator-practice observation is one playbook note, read for every incident.
PLAYBOOK_NOTE = "coordinator-practice"
_FRONTMATTER_KEYS = (
    "type",
    "title",
    "description",
    "tags",
    "status",
    "generated",
    "verified",
    "stale_after",
    "sources",
)


class PromotionUnavailable(RuntimeError):
    pass


class GitHub(Protocol):
    def file(self, path: str, ref: str) -> tuple[str, str] | None: ...
    def branch_sha(self, branch: str) -> str: ...
    def create_branch(self, branch: str, sha: str) -> None: ...
    def put_file(
        self, path: str, text: str, message: str, branch: str, sha: str | None
    ) -> None: ...
    def open_pull(self, head: str, base: str, title: str, body: str) -> dict: ...
    def label(self, number: int, labels: list[str]) -> None: ...
    def auto_merge(self, node_id: str) -> None: ...
    def pull(self, number: int) -> dict: ...
    def is_ancestor(self, sha: str, of: str) -> bool: ...


class RestGitHub:
    """The few GitHub REST and GraphQL calls promotion needs."""

    def __init__(
        self, repo: str, token: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.repo = repo
        self._http = httpx.Client(
            base_url=API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
            transport=transport,
        )

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._http.request(method, path, **kwargs)
        if response.status_code >= 400 and response.status_code != 404:
            raise RuntimeError(
                f"GitHub {method} {path}: {response.status_code} {response.text[:300]}"
            )
        return response

    def file(self, path: str, ref: str) -> tuple[str, str] | None:
        response = self._call(
            "GET", f"/repos/{self.repo}/contents/{path}", params={"ref": ref}
        )
        if response.status_code == 404:
            return None
        body = response.json()
        return base64.b64decode(body["content"]).decode("utf-8"), body["sha"]

    def branch_sha(self, branch: str) -> str:
        response = self._call("GET", f"/repos/{self.repo}/git/ref/heads/{branch}")
        if response.status_code == 404:
            raise RuntimeError(f"GitHub has no branch {branch} on {self.repo}")
        return response.json()["object"]["sha"]

    def create_branch(self, branch: str, sha: str) -> None:
        self._call(
            "POST",
            f"/repos/{self.repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )

    def put_file(
        self, path: str, text: str, message: str, branch: str, sha: str | None
    ) -> None:
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(text.encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        self._call("PUT", f"/repos/{self.repo}/contents/{path}", json=body)

    def open_pull(self, head: str, base: str, title: str, body: str) -> dict:
        return self._call(
            "POST",
            f"/repos/{self.repo}/pulls",
            json={"head": head, "base": base, "title": title, "body": body},
        ).json()

    def label(self, number: int, labels: list[str]) -> None:
        self._call(
            "POST",
            f"/repos/{self.repo}/issues/{number}/labels",
            json={"labels": labels},
        )

    def auto_merge(self, node_id: str) -> None:
        response = self._call(
            "POST",
            "/graphql",
            json={
                "query": "mutation($id: ID!) { enablePullRequestAutoMerge(input: {pullRequestId: $id, "
                "mergeMethod: SQUASH}) { clientMutationId } }",
                "variables": {"id": node_id},
            },
        )
        errors = response.json().get("errors")
        if errors:
            raise RuntimeError(f"GitHub auto-merge: {errors[0].get('message')}")

    def pull(self, number: int) -> dict:
        return self._call("GET", f"/repos/{self.repo}/pulls/{number}").json()

    def is_ancestor(self, sha: str, of: str) -> bool:
        response = self._call("GET", f"/repos/{self.repo}/compare/{sha}...{of}")
        return response.status_code != 404 and response.json().get("status") in (
            "ahead",
            "identical",
        )


def base_branch() -> str:
    return os.environ.get("PSD_GITHUB_BASE") or "main"


def unavailable_reason() -> str | None:
    if not os.environ.get("PSD_GITHUB_REPO"):
        return "PSD_GITHUB_REPO is not set"
    if not os.environ.get("PSD_GITHUB_TOKEN"):
        return "no GitHub token is configured (PSD_GITHUB_TOKEN)"
    if not learn.engine_name():
        return "no Memory Bank is configured (GOOGLE_CLOUD_AGENT_ENGINE_ID)"
    return None


_github: list[GitHub] = []


def github() -> GitHub:
    if reason := unavailable_reason():
        raise PromotionUnavailable(f"Promotion is unavailable: {reason}.")
    if not _github:
        _github.append(
            RestGitHub(os.environ["PSD_GITHUB_REPO"], os.environ["PSD_GITHUB_TOKEN"])
        )
    return _github[0]


# The note.


def note_path(scope: dict[str, str]) -> str:
    """Repository path of the note a scope's observations are promoted into."""
    (key, value), *_ = scope.items()
    folder = _SCOPES[key][0]
    name = PLAYBOOK_NOTE if key == "playbook" else re.sub(r"[^A-Za-z0-9_-]", "-", value)
    return f"{LEARNED}/{folder}/{name}.md"


def _subject(scope: dict[str, str], store: LocalStore) -> tuple[str, str, list[str]]:
    """Title, description and tags of a scope's note."""
    (key, value), *_ = scope.items()
    incidents = list(store.incidents.values())
    if key == "supplier_id":
        names = [
            i["supplier_name"]
            for i in incidents
            if i.get("supplier_id") == value and i.get("supplier_name")
        ]
        name = names[0] if names else value
        return (
            f"{name} ({value})",
            f"What the desk has learned about supplier {name} from closed incidents.",
            ["learned", "supplier"],
        )
    if key == "product_id":
        names = [
            i["product_name"]
            for i in incidents
            if i.get("product_id") == value and i.get("product_name")
        ]
        name = names[0] if names else value
        return (
            f"{name} ({value})",
            f"What the desk has learned about {name} from closed incidents.",
            ["learned", "product"],
        )
    if key == "store_id":
        return (
            f"Store {value}",
            f"How store {value} executes and verifies hold and pull tasks.",
            ["learned", "store"],
        )
    return (
        "Coordinator practice",
        "Edits coordinators make before approving, promoted as reusable guidance.",
        ["learned", "playbook", "coordinator"],
    )


def _q(value: str) -> str:
    # A JSON string is a valid YAML double-quoted scalar.
    return json.dumps(value, ensure_ascii=False)


def _instant(value: Any) -> str:
    when = knowledge.as_instant(value)
    if when is None:
        raise ValueError(f"{value!r} is not an instant with a UTC offset")
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")


def render_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    lines.append(f"type: {meta['type']}")
    lines.append(f"title: {_q(meta['title'])}")
    lines.append(f"description: {_q(meta['description'])}")
    lines.append("tags: [" + ", ".join(meta["tags"]) + "]")
    lines.append(f"status: {meta['status']}")
    generated = meta["generated"]
    lines.append(
        f"generated: {{ by: {_q(generated['by'])}, at: {_q(_instant(generated['at']))} }}"
    )
    lines.append("verified:")
    lines += [
        f"  - {{ by: {_q(v['by'])}, at: {_q(_instant(v['at']))} }}"
        for v in meta["verified"]
    ]
    lines.append(f"stale_after: {_instant(meta['stale_after'])}")
    lines.append("sources:")
    for s in meta["sources"]:
        lines += [
            f"  - id: {s['id']}",
            f"    resource: {s['resource']}",
            f"    title: {_q(s['title'])}",
        ]
    extras = {k: v for k, v in meta.items() if k not in _FRONTMATTER_KEYS}
    if extras:
        lines.append(yaml.safe_dump(extras, sort_keys=False).rstrip())
    lines.append("---")
    return "\n".join(lines) + "\n"


def _footnotes(ids: list[str]) -> str:
    return "".join(f"[^{i}]" for i in ids)


def render_note(
    existing: str | None,
    scope: dict[str, str],
    fact: str,
    sources: list[dict[str, str]],
    actor: str,
    stale_after: datetime,
    store: LocalStore,
    at: datetime,
    version: str,
) -> str:
    """The note with the fact appended, its sources merged and the coordinator's verification recorded."""
    (key, _), *_ = scope.items()
    concept_type = _SCOPES[key][1]
    title, description, tags = _subject(scope, store)
    fact = fact.strip().rstrip(".") + "." + _footnotes([s["id"] for s in sources])
    if existing:
        parsed = split_frontmatter(existing)
        if parsed is None:
            raise ValueError("the existing note has no frontmatter")
        meta, body = parsed
        known = {s["id"] for s in meta.get("sources") or []}
        meta["sources"] = list(meta.get("sources") or []) + [
            s for s in sources if s["id"] not in known
        ]
        verified = meta.get("verified") or []
        meta["verified"] = (verified if isinstance(verified, list) else [verified]) + [
            {"by": actor, "at": at}
        ]
        body = body.rstrip("\n")
        definitions = [
            line for line in body.splitlines() if re.match(r"^\[\^[^\]]+\]:", line)
        ]
        text = "\n".join(
            line for line in body.splitlines() if line not in definitions
        ).rstrip()
        entry = f"- {fact}" if concept_type == "Playbook" else fact
        body = text + ("\n" if concept_type == "Playbook" else "\n\n") + entry
    else:
        meta = {
            "type": concept_type,
            "title": title,
            "description": description,
            "tags": tags,
            "sources": sources,
            "verified": [{"by": actor, "at": at}],
        }
        if concept_type == "Playbook":
            body = (
                "# Trigger\n\nAny incident a coordinator approves; each step below is a practice coordinators "
                "verified after it recurred across approved incidents.\n\n# Steps\n\n"
                + f"- {fact}"
            )
        else:
            body = "# Observations\n\n" + fact
        definitions = []
    meta.update(
        status="stable",
        stale_after=stale_after,
        generated={"by": f"psd/promote@{version}", "at": at},
    )
    known_definitions = {line.split("]:", 1)[0] for line in definitions}
    for s in sources:
        label = f"[^{s['id']}"
        if label not in known_definitions:
            definitions.append(f"{label}]: {s['title']}.")
    return (
        render_frontmatter(meta)
        + body.rstrip()
        + "\n\n"
        + "\n".join(definitions)
        + "\n"
    )


def render_index(
    existing: str | None,
    scope: dict[str, str],
    path: str,
    title: str,
    description: str,
) -> str:
    """knowledge/learned/index.md with the note listed under its section, sections in a fixed order."""
    (key, _), *_ = scope.items()
    relative = path.removeprefix(f"{LEARNED}/")
    text = existing or "# Learned\n"
    head, _, rest = text.partition("\n## ")
    sections: dict[str, list[str]] = {name: [] for _, _, name in _SCOPES.values()}
    for block in ("## " + rest).split("\n## ") if rest else []:
        name, _, entries = block.removeprefix("## ").partition("\n")
        sections.setdefault(name.strip(), []).extend(
            line for line in entries.splitlines() if line.startswith("* [")
        )
    entries = sections[_SCOPES[key][2]]
    if not any(f"]({relative})" in line for line in entries):
        entries.append(f"* [{title}]({relative}) - {description}")
    out = head.rstrip("\n") + "\n"
    for name, lines in sections.items():
        if lines:
            out += f"\n## {name}\n\n" + "\n".join(sorted(lines)) + "\n"
    return out


def render_log(existing: str | None, day: str, entry: str) -> str:
    """knowledge/learned/log.md with the entry under today's heading, newest first."""
    text = existing or "# Log\n"
    heading = f"## {day}"
    if heading in text:
        return text.replace(heading + "\n", f"{heading}\n\n{entry}\n", 1)
    head, sep, rest = text.partition("\n## ")
    return (
        head.rstrip("\n")
        + f"\n\n{heading}\n\n{entry}\n"
        + (f"\n## {rest}" if sep else "")
    )


# What the routes call.


def linked(store: LocalStore, memory_name: str) -> list[dict[str, Any]]:
    return [
        link
        for link in store.memory_links.values()
        if memory_name in link.get("memory_names", []) and link["status"] == "generated"
    ]


def _source(store: LocalStore, incident_id: str) -> dict[str, str]:
    incident = store.incidents.get(incident_id) or {}
    what = f"{incident.get('kind', 'incident')} for {incident.get('hazard_type', 'an unknown hazard')}"
    on = incident.get("product_name") or incident.get("product_id") or "a product"
    when = (
        incident.get("approved_at")
        or incident.get("dismissed_at")
        or incident.get("created_at")
        or ""
    )[:10]
    outcome = (
        "approved"
        if incident.get("approved_at")
        else "dismissed"
        if incident.get("dismissed_at")
        else "raised"
    )
    return {
        "id": incident_id,
        "resource": f"incidents/{incident_id}",
        "title": f"Incident {incident_id}, {what} on {on}, {outcome} {when}".rstrip(),
    }


def promote(
    store: LocalStore,
    memory_name: str,
    fact: str,
    actor: str,
    stale_after: datetime,
    gh: GitHub,
    version: str,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Opens the promotion pull request for one observation, or returns the one already open."""
    links = linked(store, memory_name)
    if not links:
        raise LookupError(f"No observation {memory_name} the desk generated")
    if open_pr := next((link for link in links if link.get("promotion_pr")), None):
        return {
            "pr": open_pr["promotion_pr"],
            "url": open_pr.get("promotion_url"),
            "path": open_pr.get("promotion_path"),
            "already_open": True,
        }
    if not actor.startswith("human:"):
        actor = f"human:{actor}"
    at = at or datetime.now(UTC)
    if stale_after <= at:
        raise ValueError("stale_after must be in the future")
    scope = links[0]["scope"]
    path = note_path(scope)
    sources = [
        _source(store, i) for i in dict.fromkeys(link["incident_id"] for link in links)
    ]
    base = base_branch()
    base_sha = gh.branch_sha(base)
    # A new branch per attempt, so a retry after a half-finished one never meets that one's commits.
    branch = f"promote/{memory_name.rsplit('/', 1)[-1]}-{int(at.timestamp())}"
    gh.create_branch(branch, base_sha)
    existing = gh.file(path, base)
    note = render_note(
        existing[0] if existing else None,
        scope,
        fact,
        sources,
        actor,
        stale_after,
        store,
        at,
        version,
    )
    title, description, _ = _subject(scope, store)
    gh.put_file(
        path, note, f"promote: {path}", branch, existing[1] if existing else None
    )
    index = gh.file(f"{LEARNED}/index.md", base)
    gh.put_file(
        f"{LEARNED}/index.md",
        render_index(index[0] if index else None, scope, path, title, description),
        f"promote: list {path}",
        branch,
        index[1] if index else None,
    )
    log = gh.file(f"{LEARNED}/log.md", base)
    gh.put_file(
        f"{LEARNED}/log.md",
        render_log(
            log[0] if log else None,
            at.date().isoformat(),
            f"**Update** Promoted an observation into [{title}]({path.removeprefix(LEARNED + '/')}), verified by "
            f"{actor}.",
        ),
        f"promote: log {path}",
        branch,
        log[1] if log else None,
    )
    pr = gh.open_pull(
        head=branch,
        base=base,
        title=f"promote: {path}",
        body=(
            f"Observation `{memory_name}`, verified by {actor}, promoted into `{path}` (stale after "
            f"{_instant(stale_after)}).\n\nSources: "
            + ", ".join(s["id"] for s in sources)
            + ".\n\n"
            f"Touches only `{LEARNED}/**`. Written by the desk's promotion step."
        ),
    )
    gh.label(pr["number"], [LABEL])
    auto_merge = None
    try:
        gh.auto_merge(pr["node_id"])
    except Exception as e:
        auto_merge = str(e)[:300]
        logger.warning("auto-merge not enabled on #%s: %s", pr["number"], auto_merge)
    for link in links:
        store.update_link(
            link["link_id"],
            promotion_pr=pr["number"],
            promotion_url=pr.get("html_url"),
            promotion_path=path,
            promoted_by=actor,
            promotion_requested_at=now(),
        )
    store.append_audit(
        actor,
        "promote_observation",
        "memory",
        memory_name,
        after={"path": path, "pr": pr["number"], "stale_after": _instant(stale_after)},
    )
    return {
        "pr": pr["number"],
        "url": pr.get("html_url"),
        "path": path,
        "already_open": False,
        "auto_merge_error": auto_merge,
    }


def settle(store: LocalStore, deployed_sha: str, gh: GitHub) -> dict[str, int]:
    """After a deploy: merged and deployed promotions delete their memory; closed ones return to retrieval."""
    settled = returned = waiting = 0
    by_pr: dict[int, list[dict[str, Any]]] = {}
    for link in store.memory_links.values():
        if link.get("promotion_pr") and link["status"] == "generated":
            by_pr.setdefault(link["promotion_pr"], []).append(link)
    for number, links in by_pr.items():
        pr = gh.pull(number)
        if (
            pr.get("merged")
            and pr.get("merge_commit_sha")
            and gh.is_ancestor(pr["merge_commit_sha"], deployed_sha)
        ):
            names = sorted({n for link in links for n in link["memory_names"]})
            for name in names:
                try:
                    learn.memories().delete(name=name)
                except Exception as e:
                    logger.warning("could not delete promoted memory %s: %s", name, e)
            for link in links:
                store.update_link(
                    link["link_id"],
                    status="promoted",
                    promoted_to=link.get("promotion_path"),
                    commit=pr["merge_commit_sha"],
                    promoted_at=now(),
                )
            store.append_audit(
                "process:promotion-settle",
                "settle_promotion",
                "pull_request",
                str(number),
                after={"memories": names, "commit": pr["merge_commit_sha"]},
            )
            settled += 1
        elif pr.get("state") == "closed" and not pr.get("merged"):
            for link in links:
                store.update_link(
                    link["link_id"],
                    promotion_pr=None,
                    promotion_url=None,
                    promotion_closed_at=now(),
                )
            store.append_audit(
                "process:promotion-settle",
                "return_observation",
                "pull_request",
                str(number),
            )
            returned += 1
        else:
            waiting += 1
    return {"settled": settled, "returned": returned, "waiting": waiting}


def delete_observation(
    store: LocalStore, memory_name: str, actor: str
) -> dict[str, Any]:
    """Deletes one observation from Memory Bank and drops it from every link that named it."""
    links = [
        link
        for link in store.memory_links.values()
        if memory_name in link.get("memory_names", [])
    ]
    if any(link.get("promotion_pr") for link in links):
        raise ValueError(
            "This observation has an open promotion pull request; close it first."
        )
    learn.memories().delete(name=memory_name)
    for link in links:
        names = [n for n in link["memory_names"] if n != memory_name]
        store.update_link(
            link["link_id"],
            memory_names=names,
            **({"status": "deleted", "deleted_at": now()} if not names else {}),
        )
    store.append_audit(actor, "delete_observation", "memory", memory_name)
    return {"deleted": memory_name, "links": len(links)}


def observations(store: LocalStore) -> list[dict[str, Any]]:
    """Every observation in Memory Bank, with its source incidents and promotion state."""
    name = learn.engine_name()
    if not name:
        return []
    by_memory: dict[str, list[dict[str, Any]]] = {}
    for link in store.memory_links.values():
        for memory_name in link.get("memory_names", []):
            by_memory.setdefault(memory_name, []).append(link)
    out = []
    for memory in learn.memories().list(name=name):
        links = by_memory.get(memory.name, [])
        promoting = next((link for link in links if link.get("promotion_pr")), None)
        out.append(
            {
                "name": memory.name,
                "id": memory.name.rsplit("/", 1)[-1],
                "fact": memory.fact,
                "scope": dict(memory.scope or {}),
                "topics": [
                    getattr(t, "custom_memory_topic_label", None) or str(t)
                    for t in memory.topics or []
                ],
                "updated": _iso(getattr(memory, "update_time", None)),
                "expires": _iso(getattr(memory, "expire_time", None)),
                "incidents": sorted({link["incident_id"] for link in links}),
                "promotion": (
                    {
                        "pr": promoting["promotion_pr"],
                        "url": promoting.get("promotion_url"),
                        "path": promoting.get("promotion_path"),
                    }
                    if promoting
                    else None
                ),
            }
        )
    return sorted(
        out, key=lambda o: (json.dumps(o["scope"], sort_keys=True), o["updated"] or "")
    )


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    return str(value) if value else None
