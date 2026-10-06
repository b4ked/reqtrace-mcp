"""Change impact: which requirements and tests a git diff touches.

Both sides of the diff are mapped: new-side lines to current functions, old-side lines to the
functions as they were at `base_ref` (so deleting a function still flags its requirements).
Requirement text changes are detected by parsing the requirement files at `base_ref`.
"""

from __future__ import annotations

import contextlib
import re
import subprocess

from . import requirements as reqmod
from .analysis import Context, verifying_tests
from .annotations import is_test_path, scan_text, suffixes, test_nodeid
from .config import ReqtraceError, rel
from .model import CodeItem, ImpactResult
from .state import latest_reviews

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
REF_RE = re.compile(r"^[A-Za-z0-9._/~^@{}-]+$")


def _git(ctx: Context, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=ctx.cfg.root, capture_output=True, text=True, timeout=60
    )
    if check and proc.returncode != 0:
        raise ReqtraceError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[-300:]}")
    return proc.stdout


def _parse_diff(diff: str) -> dict[str, tuple[set[int], set[int], str | None]]:
    """path -> (old changed lines, new changed lines, old path)."""
    out: dict[str, tuple[set[int], set[int], str | None]] = {}
    old_path: str | None = None
    cur: str | None = None
    for line in diff.splitlines():
        if line.startswith("--- "):
            old_path = None if line[4:] == "/dev/null" else line[6:]
        elif line.startswith("+++ "):
            cur = (line[6:] if line[4:] != "/dev/null" else old_path) or ""
            out.setdefault(cur, (set(), set(), old_path))
        elif cur is not None and (m := HUNK_RE.match(line)):
            a, b = int(m.group(1)), int(m.group(2) or 1)
            c, d = int(m.group(3)), int(m.group(4) or 1)
            old_l, new_l, _ = out[cur]
            old_l.update(range(a, a + b) if b else {a})
            new_l.update(range(c, c + d) if d else {c, c + 1})
    return out


def _hit(items: list[CodeItem], lines: set[int]) -> list[CodeItem]:
    # Innermost match wins for methods, but a class header change also hits the class.
    return [i for i in items if any(i.start_line <= ln <= i.end_line for ln in lines)]


def impact_of_change(
    ctx: Context, base_ref: str = "HEAD", include_uncommitted: bool = True
) -> ImpactResult:
    if base_ref.startswith("-") or not REF_RE.match(base_ref):
        raise ReqtraceError(f"Invalid git ref {base_ref!r}")
    if _git(ctx, "rev-parse", "--is-inside-work-tree", check=False).strip() != "true":
        raise ReqtraceError("Change impact needs a git repository")
    _git(ctx, "rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}")

    diff_args = ["diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", base_ref]
    if not include_uncommitted:
        diff_args.append("HEAD")
    changes = _parse_diff(_git(ctx, *diff_args, "--"))
    code_sfx = suffixes(ctx.cfg)
    if include_uncommitted:
        for path in _git(ctx, "ls-files", "--others", "--exclude-standard").splitlines():
            full = ctx.cfg.root / path
            if full.name.lower().endswith((*code_sfx, ".yaml", ".yml")) and full.is_file():
                n = len(full.read_text(encoding="utf-8", errors="replace").splitlines())
                changes[path] = (set(), set(range(1, n + 1)), None)

    affected: dict[str, list[str]] = {}
    changed_items: list[str] = []
    rerun: set[str] = set()

    def note(rid: str, reason: str) -> None:
        affected.setdefault(rid, [])
        if reason not in affected[rid]:
            affected[rid].append(reason)

    current: dict[str, list[CodeItem]] = {
        i.path: [] for i in [*ctx.scan.source_items, *ctx.scan.test_items]
    }
    for i in [*ctx.scan.source_items, *ctx.scan.test_items]:
        current[i.path].append(i)
    test_paths = {i.path for i in ctx.scan.test_items}

    for path, (old_lines, new_lines, old_path) in changes.items():
        if not path.lower().endswith(code_sfx):
            continue
        is_test = (
            path in test_paths
            or is_test_path(ctx.cfg, path)
            or (not ctx.cfg.is_cpp and "test" in path.split("/")[-1])
        )
        hits = _hit(current.get(path, []), new_lines)
        if old_path and old_lines:
            old_text = _git(ctx, "show", f"{base_ref}:{old_path}", check=False)
            if old_text:
                with contextlib.suppress(SyntaxError):
                    hits += _hit(scan_text(old_text, old_path, is_test), old_lines)
        for item in {h.id: h for h in hits}.values():
            changed_items.append(item.id)
            for rid in item.implements:
                note(rid, f"implementing code changed: {item.id}")
            for rid in item.verifies:
                note(rid, f"verifying test changed: {item.id}")
            if is_test and item.kind != "class" and (item.kind == "test" or not ctx.cfg.is_cpp):
                rerun.add(test_nodeid(item))

    # Requirement text changes
    req_base = ctx.cfg.root / ctx.cfg.requirements
    for path in changes:
        full = ctx.cfg.root / path
        if not path.endswith((".yaml", ".yml")):
            continue
        try:
            full.resolve().relative_to(req_base.resolve())
        except ValueError:
            continue
        old = {
            r.id: r
            for r in reqmod.parse_requirements_text(
                _git(ctx, "show", f"{base_ref}:{path}", check=False), path
            )
        }
        new = {
            r.id: r
            for r in (
                reqmod.parse_requirements_text(
                    full.read_text(encoding="utf-8"), rel(ctx.cfg.root, full)
                )
                if full.exists()
                else []
            )
        }
        for rid in old.keys() | new.keys():
            if rid not in new:
                note(rid, "requirement deleted")
            elif rid not in old:
                note(rid, "requirement added")
            elif (old[rid].text, old[rid].acceptance) != (new[rid].text, new[rid].acceptance):
                note(rid, "requirement text or acceptance changed")

    for rid in affected:
        rerun.update(verifying_tests(ctx, rid))
    reviews = latest_reviews(ctx.cfg)
    return ImpactResult(
        base_ref=base_ref,
        include_uncommitted=include_uncommitted,
        changed_files=sorted(changes),
        changed_items=sorted(set(changed_items)),
        affected_requirements=dict(sorted(affected.items())),
        tests_to_rerun=sorted(rerun),
        reviews_invalidated=sorted(r for r in affected if r in reviews),
    )
