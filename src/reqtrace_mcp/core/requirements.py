"""Load, validate and lint YAML requirements."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .config import Config, ReqtraceError, rel, safe_path
from .model import LintFinding, Requirement

ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
VAGUE_WORDS = [
    "fast",
    "quickly",
    "appropriate",
    "appropriately",
    "as needed",
    "as required",
    "user-friendly",
    "robust",
    "efficient",
    "adequate",
    "reasonable",
    "etc",
    "and/or",
    "some",
    "several",
    "normally",
    "usually",
    "where possible",
    "if possible",
]
_VAGUE_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in VAGUE_WORDS) + r")\b", re.I)
FIELDS = {"id", "title", "text", "rationale", "acceptance", "parent", "tags"}


def requirement_files(cfg: Config) -> list[Path]:
    base = safe_path(cfg.root, cfg.requirements)
    if base.is_file():
        return [base]
    if not base.is_dir():
        raise ReqtraceError(
            f"No requirements found at {cfg.requirements!r}. Create YAML files there "
            "(see docs/SPEC.md §3.1) or set `requirements:` in .reqtrace.yaml."
        )
    return sorted([*base.rglob("*.yaml"), *base.rglob("*.yml")])


class _LineLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _LineLoader, node: yaml.MappingNode) -> dict[str, Any]:
    mapping: dict[str, Any] = dict(loader.construct_mapping(node, deep=True))  # type: ignore[arg-type]
    mapping["__line__"] = node.start_mark.line + 1
    return mapping


_LineLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _parse_text(text: str, source: str) -> list[Requirement]:
    try:
        data = yaml.load(text, Loader=_LineLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        raise ReqtraceError(f"{source}: invalid YAML: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, list):
        raise ReqtraceError(f"{source}: expected a list of requirements")
    out: list[Requirement] = []
    for item in data:
        if not isinstance(item, dict):
            raise ReqtraceError(f"{source}: each requirement must be a mapping")
        line = item.pop("__line__", 0)
        where = f"{source}:{line}"
        unknown = set(item) - FIELDS
        if unknown:
            raise ReqtraceError(f"{where}: unknown fields {sorted(unknown)}")
        rid = str(item.get("id", ""))
        if not ID_RE.match(rid):
            raise ReqtraceError(f"{where}: id {rid!r} must look like REQ-001")
        if not str(item.get("text", "")).strip():
            raise ReqtraceError(f"{where}: {rid} has no text")
        acc = item.get("acceptance") or []
        if not isinstance(acc, list):
            raise ReqtraceError(f"{where}: {rid} acceptance must be a list")
        out.append(
            Requirement(
                id=rid,
                title=str(item.get("title", "")),
                text=str(item["text"]).strip(),
                rationale=str(item.get("rationale", "") or ""),
                acceptance=[str(a) for a in acc],
                parent=str(item["parent"]) if item.get("parent") else None,
                tags=[str(t) for t in item.get("tags") or []],
                source=where,
            )
        )
    return out


def load_requirements(cfg: Config) -> list[Requirement]:
    reqs: list[Requirement] = []
    seen: dict[str, str] = {}
    for f in requirement_files(cfg):
        for r in _parse_text(f.read_text(encoding="utf-8"), rel(cfg.root, f)):
            if r.id in seen:
                raise ReqtraceError(
                    f"Duplicate requirement id {r.id} at {r.source} and {seen[r.id]}"
                )
            seen[r.id] = r.source
            reqs.append(r)
    return reqs


def parse_requirements_text(text: str, source: str) -> list[Requirement]:
    """Parse requirements from a string (used for diffing against an older git revision)."""
    return _parse_text(text, source)


def lint(reqs: list[Requirement]) -> list[LintFinding]:
    """Deterministic quality checks. Ambiguity and conflicts need judgement; agents flag those."""
    findings: list[LintFinding] = []
    ids = {r.id for r in reqs}
    for r in reqs:
        if not r.acceptance:
            findings.append(
                LintFinding(
                    req_id=r.id,
                    severity="warning",
                    source=r.source,
                    message="No acceptance criteria: tests cannot be checked "
                    "against an agreed boundary",
                )
            )
        if not re.search(r"\bshall\b", r.text, re.I):
            findings.append(
                LintFinding(
                    req_id=r.id,
                    severity="warning",
                    source=r.source,
                    message="Text does not use 'shall'; is this binding?",
                )
            )
        vague = sorted({m.group(0).lower() for m in _VAGUE_RE.finditer(r.text)})
        if vague:
            findings.append(
                LintFinding(
                    req_id=r.id,
                    severity="warning",
                    source=r.source,
                    message=f"Vague wording {vague}: not objectively testable",
                )
            )
        if r.parent and r.parent not in ids and r.parent.split("-")[0] == r.id.split("-")[0]:
            findings.append(
                LintFinding(
                    req_id=r.id,
                    severity="error",
                    source=r.source,
                    message=f"Parent {r.parent} is not defined",
                )
            )
        if len(re.findall(r"\bshall\b", r.text, re.I)) > 1:
            findings.append(
                LintFinding(
                    req_id=r.id,
                    severity="warning",
                    source=r.source,
                    message="More than one 'shall': consider splitting so each "
                    "requirement is verified separately",
                )
            )
    return findings
