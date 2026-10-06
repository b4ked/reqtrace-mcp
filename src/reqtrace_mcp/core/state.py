"""Persistent evidence state under `.reqtrace/`: reviews, issues, suggested links.

Reviews and suggestions store a content hash of what they covered (requirement text plus the
source of the implementing code and linked tests). If any of it changes, they become stale:
sign-off is tied to exact content, never to a requirement ID alone.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml

from .annotations import ScanResult, item_source
from .config import Config, ReqtraceError
from .model import Issue, Requirement, Review, Suggestion


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def requirement_hash(
    cfg: Config,
    req: Requirement,
    scan: ScanResult,
    extra_links: list[tuple[str, str]] | None = None,
) -> str:
    """Hash of requirement text + acceptance + source of every linked code item and test."""
    h = hashlib.sha256()
    h.update(f"{req.id}\n{req.text}\n{json.dumps(req.acceptance)}\n".encode())
    targets = sorted(
        {i.id for i in scan.source_items if req.id in i.implements}
        | {i.id for i in scan.test_items if req.id in i.verifies}
        | {t for (rid, t) in (extra_links or []) if rid == req.id}
    )
    items = scan.by_id()
    for t in targets:
        h.update(t.encode())
        if t in items:
            h.update(item_source(cfg, items[t]).encode())
    return h.hexdigest()[:16]


def _append_jsonl(path: Path, record: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record + "\n")


def _read_jsonl(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ------------------------------------------------------------------ reviews ---


def reviews_path(cfg: Config) -> Path:
    return cfg.state_dir / "reviews.jsonl"


def load_reviews(cfg: Config) -> list[Review]:
    return [Review.model_validate_json(ln) for ln in _read_jsonl(reviews_path(cfg))]


def record_review(
    cfg: Config,
    req: Requirement,
    scan: ScanResult,
    decision: Literal["approved", "rejected"],
    reviewer: str,
    rationale: str,
    extra_links: list[tuple[str, str]] | None = None,
) -> Review:
    if not reviewer.strip():
        raise ReqtraceError("A review needs a named human reviewer")
    if not rationale.strip():
        raise ReqtraceError("A review needs a rationale")
    review = Review(
        req_id=req.id,
        decision=decision,
        reviewer=reviewer.strip(),
        rationale=rationale.strip(),
        timestamp=now(),
        content_hash=requirement_hash(cfg, req, scan, extra_links),
    )
    _append_jsonl(reviews_path(cfg), review.model_dump_json())
    return review


def latest_reviews(cfg: Config) -> dict[str, Review]:
    out: dict[str, Review] = {}
    for r in load_reviews(cfg):
        out[r.req_id] = r
    return out


# ------------------------------------------------------------------- issues ---


def issues_path(cfg: Config) -> Path:
    return cfg.state_dir / "issues.jsonl"


def load_issues(cfg: Config) -> list[Issue]:
    return [Issue.model_validate_json(ln) for ln in _read_jsonl(issues_path(cfg))]


def flag_issue(
    cfg: Config,
    req_id: str,
    kind: str,
    description: str,
    raised_by: str,
    related: list[str] | None = None,
) -> Issue:
    if not description.strip():
        raise ReqtraceError("Describe the issue so a human can resolve it")
    issue = Issue(
        id=f"ISS-{secrets.token_hex(3)}",
        req_id=req_id,
        kind=kind,  # type: ignore[arg-type]
        description=description.strip(),
        raised_by=raised_by,
        timestamp=now(),
        related=related or [],
    )
    _append_jsonl(issues_path(cfg), issue.model_dump_json())
    return issue


# -------------------------------------------------------------- suggestions ---


def suggestions_path(cfg: Config) -> Path:
    return cfg.state_dir / "suggested_links.yaml"


def load_suggestions(cfg: Config) -> list[Suggestion]:
    p = suggestions_path(cfg)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return [Suggestion.model_validate(d) for d in data]


def save_suggestions(cfg: Config, items: list[Suggestion]) -> None:
    p = suggestions_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump([s.model_dump() for s in items], sort_keys=False), encoding="utf-8")


def item_hash(cfg: Config, scan: ScanResult, target: str) -> str:
    items = scan.by_id()
    src = item_source(cfg, items[target]) if target in items else ""
    return hashlib.sha256(src.encode()).hexdigest()[:16]


def add_suggestion(
    cfg: Config, scan: ScanResult, req_id: str, kind: str, target: str, rationale: str
) -> Suggestion:
    items = scan.by_id()
    if target not in items:
        raise ReqtraceError(
            f"Unknown target {target!r}. Use path::qualname as listed by "
            "trace_matrix (e.g. src/pkg/mod.py::func)."
        )
    existing = load_suggestions(cfg)
    for s in existing:
        if (s.req_id, s.kind, s.target) == (req_id, kind, target) and s.status != "rejected":
            return s
    sug = Suggestion(
        id=f"SUG-{secrets.token_hex(3)}",
        req_id=req_id,
        kind=kind,  # type: ignore[arg-type]
        target=target,
        rationale=rationale,
        proposed_at=now(),
        content_hash=item_hash(cfg, scan, target),
    )
    save_suggestions(cfg, [*existing, sug])
    return sug


def set_suggestion_status(
    cfg: Config, sug_id: str, status: Literal["accepted", "rejected"]
) -> Suggestion:
    items = load_suggestions(cfg)
    for s in items:
        if s.id == sug_id:
            s.status = status
            save_suggestions(cfg, items)
            return s
    raise ReqtraceError(f"No suggestion {sug_id}")
