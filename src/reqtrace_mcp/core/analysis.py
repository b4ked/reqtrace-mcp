"""Trace matrix, requirement status and gap analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import requirements as reqmod
from .annotations import ScanResult, is_ignored, scan, test_nodeid
from .config import Config
from .model import CodeItem, Gap, Matrix, Requirement, RequirementTrace, RunSummary, Status
from .runner import PARAM_RE, CoverageIndex, fingerprint, load_run, run_fingerprint
from .state import (
    item_hash,
    latest_reviews,
    load_issues,
    load_suggestions,
    now,
    requirement_hash,
)


@dataclass
class Context:
    """Everything loaded once per analysis."""

    cfg: Config
    reqs: list[Requirement]
    scan: ScanResult
    run: RunSummary | None
    cov: CoverageIndex | None
    results_stale: bool
    accepted: list[tuple[str, str, str]] = field(default_factory=list)  # (req, kind, target)

    @property
    def extra_links(self) -> list[tuple[str, str]]:
        return [(r, t) for (r, _k, t) in self.accepted]


def load_context(cfg: Config) -> Context:
    reqs = reqmod.load_requirements(cfg)
    sc = scan(cfg)
    run = load_run(cfg)
    cov = CoverageIndex(cfg, run.run_id) if run else None
    stale = bool(run) and run_fingerprint(cfg, run.run_id) != fingerprint(cfg)  # type: ignore[union-attr]
    accepted: list[tuple[str, str, str]] = [
        (s.req_id, str(s.kind), s.target) for s in load_suggestions(cfg) if s.status == "accepted"
    ]
    return Context(cfg, reqs, sc, run, cov, stale, accepted)


def _is_test_fn(item: CodeItem) -> bool:
    if item.kind == "test":  # C/C++: GoogleTest TEST(...) or an annotated test main
        return True
    return item.kind != "class" and item.qualname.split(".")[-1].startswith("test")


def implementing_items(ctx: Context, req_id: str) -> list[CodeItem]:
    items = ctx.scan.by_id()
    linked_classes = {
        i.qualname for i in ctx.scan.source_items if i.kind == "class" and req_id in i.implements
    }
    out = [
        i
        for i in ctx.scan.source_items
        if req_id in i.implements
        or (i.kind == "method" and i.qualname.split(".")[0] in linked_classes)
    ]
    out += [
        items[t] for (r, k, t) in ctx.accepted if r == req_id and k == "implements" and t in items
    ]
    return list({i.id: i for i in out}.values())


def verifying_tests(ctx: Context, req_id: str) -> list[str]:
    """Node ids (without parametrize suffix) of tests linked to the requirement."""
    ids = {test_nodeid(i) for i in ctx.scan.test_items if _is_test_fn(i) and req_id in i.verifies}
    items = ctx.scan.by_id()
    ids |= {
        test_nodeid(items[t])
        for (r, k, t) in ctx.accepted
        if r == req_id and k == "verifies" and t in items
    }
    if ctx.run:  # markers applied dynamically (e.g. pytest.param marks) only show at runtime
        ids |= {PARAM_RE.sub("", t.nodeid) for t in ctx.run.tests if req_id in t.verifies}
    return sorted(ids)


def _outcomes(run: RunSummary | None) -> dict[str, str]:
    """Aggregate parametrised cases: failed/error beats skipped beats passed."""
    agg: dict[str, str] = {}
    rank = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}
    for t in run.tests if run else []:
        base = PARAM_RE.sub("", t.nodeid)
        prev = agg.get(base)
        if prev is None or rank[t.outcome] > rank[prev]:
            agg[base] = t.outcome
    return agg


def trace(ctx: Context, req: Requirement, outcomes: dict[str, str]) -> RequirementTrace:
    impl = implementing_items(ctx, req.id)
    tests = verifying_tests(ctx, req.id)
    results = {t: outcomes.get(t, "not_run") for t in tests}
    spans = [(i.path, i.body_start, i.end_line) for i in impl]
    exercising = [
        t
        for t in tests
        if results[t] == "passed"
        and ctx.cov
        and any(ctx.cov.test_hits(t, p, a, b) for p, a, b in spans)
    ]
    unexercised: list[str] = []
    if exercising and ctx.cov:
        for i in impl:
            if any(ctx.cov.test_hits(t, i.path, i.body_start, i.end_line) for t in exercising):
                continue
            built = ctx.cov.has_lines(i.path, i.body_start, i.end_line)
            unexercised.append(
                i.id
                if built
                else f"{i.id} (no coverage data: not compiled or not measured in this run)"
            )
    reviews = latest_reviews(ctx.cfg)
    review = reviews.get(req.id)
    review_current = bool(review) and review.content_hash == requirement_hash(  # type: ignore[union-attr]
        ctx.cfg, req, ctx.scan, ctx.extra_links
    )
    open_issues = sum(1 for i in load_issues(ctx.cfg) if i.req_id == req.id)

    if not impl:
        status = Status.NOT_IMPLEMENTED
    elif not tests:
        status = Status.NOT_VERIFIED
    elif any(v in ("failed", "error") for v in results.values()):
        status = Status.FAILING
    elif all(v in ("not_run", "skipped") for v in results.values()):
        status = Status.NOT_RUN
    elif not exercising:
        status = Status.WEAKLY_VERIFIED
    elif review_current and review.decision == "approved":  # type: ignore[union-attr]
        status = Status.REVIEWED
    else:
        status = Status.VERIFIED

    return RequirementTrace(
        requirement=req,
        status=status,
        implemented_by=[i.id for i in impl],
        verified_by=tests,
        test_results=results,
        tests_exercising_code=exercising,
        coverage=ctx.cov.figures(spans) if ctx.cov and ctx.cov.available and spans else None,
        unexercised_code=unexercised,
        review=(
            f"{review.decision} by {review.reviewer} ({review.timestamp})"
            + ("" if review_current else " — STALE: content changed since review")
        )
        if review
        else None,
        open_issues=open_issues,
    )


def unrequired_code(ctx: Context) -> list[str]:
    """Public source items that no requirement asked for and are not marked `derived`."""
    cfg = ctx.cfg
    accepted_impl = {t for (_r, k, t) in ctx.accepted if k == "implements"}

    def linked(i: CodeItem) -> bool:
        return bool(i.implements) or i.derived is not None or i.id in accepted_impl

    def private(qual: str) -> bool:
        return any(part.startswith("_") for part in qual.split("."))

    classes = {i.qualname: i for i in ctx.scan.source_items if i.kind == "class"}
    flagged: list[str] = []
    for i in ctx.scan.source_items:
        if is_ignored(cfg, i.path) or (cfg.ignore_private and private(i.qualname)):
            continue
        if i.kind == "method":
            cls = classes.get(i.qualname.split(".")[0])
            if (
                cls is None
                or linked(cls)
                or cls.id in flagged
                or i.qualname.split(".")[-1].startswith("__")
            ):
                continue
            if not linked(i):
                flagged.append(i.id)
        elif i.kind == "class":
            methods = [
                m
                for m in ctx.scan.source_items
                if m.kind == "method"
                and m.path == i.path
                and m.qualname.startswith(i.qualname + ".")
            ]
            if not linked(i) and not any(linked(m) for m in methods):
                flagged.append(i.id)
        elif not linked(i):
            flagged.append(i.id)
    return flagged


def dangling_links(ctx: Context) -> list[str]:
    known = {r.id for r in ctx.reqs}
    out = []
    for i in ctx.scan.source_items:
        out += [f"{i.id} implements unknown {r}" for r in i.implements if r not in known]
    for i in ctx.scan.test_items:
        out += [f"{i.id} verifies unknown {r}" for r in i.verifies if r not in known]
    return out


def build_matrix(ctx: Context) -> Matrix:
    outcomes = _outcomes(ctx.run)
    return Matrix(
        generated_at=now(),
        run_id=ctx.run.run_id if ctx.run else None,
        requirements=[trace(ctx, r, outcomes) for r in ctx.reqs],
        unrequired_code=unrequired_code(ctx),
        dangling_links=dangling_links(ctx),
    )


def _failure_lines(ctx: Context, bases: list[str]) -> list[str]:
    """Each failing case (with parametrize id) and the last line of its error."""
    out = []
    for t in ctx.run.tests if ctx.run else []:
        if PARAM_RE.sub("", t.nodeid) in bases and t.outcome in ("failed", "error"):
            lines = [ln.strip() for ln in t.message.splitlines() if ln.strip()]
            errs = [ln[1:].strip() for ln in lines if ln.startswith("E ")]
            last = " / ".join(errs[:2]) if errs else (lines[-1] if lines else "")
            out.append(f"{t.nodeid} ({last[:200]})" if last else t.nodeid)
    return out or bases


_NEXT = {
    Status.NOT_IMPLEMENTED: (
        "unimplemented",
        "Implement it and add `# implements: {id}` above the implementing function.",
    ),
    Status.NOT_VERIFIED: (
        "untested",
        'Write tests marked `@pytest.mark.verifies("{id}")` that '
        "check each acceptance criterion, including boundaries.",
    ),
    Status.NOT_RUN: ("not_run", "Run verification."),
    Status.FAILING: (
        "failing",
        "Fix the code or the test; if the requirement itself is wrong, "
        "flag it rather than changing the test to pass.",
    ),
    Status.WEAKLY_VERIFIED: (
        "weakly_verified",
        "The linked tests never execute the implementing "
        "code. Make them call it, or fix the `implements` link.",
    ),
}


_NEXT_CPP = {
    Status.NOT_IMPLEMENTED: (
        "unimplemented",
        "Implement it and add `// implements: {id}` above the implementing function.",
    ),
    Status.NOT_VERIFIED: (
        "untested",
        "Write tests with `// verifies: {id}` above each TEST(...) (or above `main` of a test "
        "executable) that check each acceptance criterion, including boundaries.",
    ),
}


def find_gaps(ctx: Context, matrix: Matrix | None = None) -> list[Gap]:
    m = matrix or build_matrix(ctx)
    gaps: list[Gap] = []
    if ctx.results_stale:
        gaps.append(
            Gap(
                kind="not_run",
                detail="Source or tests changed since the last "
                "verification run; results are stale.",
                next_action="Run verification.",
            )
        )
    for t in m.requirements:
        rid = t.requirement.id
        if t.status in _NEXT:
            kind, action = (_NEXT_CPP if ctx.cfg.is_cpp else {}).get(t.status, _NEXT[t.status])
            failing = _failure_lines(
                ctx, [n for n, v in t.test_results.items() if v in ("failed", "error")]
            )
            detail = {
                "failing": "Failing: " + "; ".join(failing),
                "weakly_verified": f"Tests {', '.join(t.verified_by)} pass but do not execute "
                f"{', '.join(t.implemented_by)}",
            }.get(kind, f"{rid}: {t.status.value}")
            gaps.append(
                Gap(
                    kind=kind,  # type: ignore[arg-type]
                    req_id=rid,
                    location=t.requirement.source,
                    detail=detail,
                    next_action=action.format(id=rid),
                )
            )
        if (
            t.coverage
            and t.coverage.missing_branches
            and t.status in (Status.VERIFIED, Status.REVIEWED, Status.WEAKLY_VERIFIED)
        ):
            gaps.append(
                Gap(
                    kind="uncovered_branch",
                    req_id=rid,
                    location=", ".join(t.coverage.missing_branches[:5]),
                    detail=f"{len(t.coverage.missing_branches)} branch(es) in "
                    "implementing code never taken by any test",
                    next_action="Add a test for the untaken branch, or remove dead code.",
                )
            )
        if t.unexercised_code and t.status in (Status.VERIFIED, Status.REVIEWED):
            gaps.append(
                Gap(
                    kind="unexercised_code",
                    req_id=rid,
                    location=", ".join(t.unexercised_code[:5]),
                    detail=f"No passing test linked to {rid} executes "
                    + "; ".join(t.unexercised_code),
                    next_action=f"Add a test linked to {rid} that calls it, or fix the "
                    "`implements` link. Code not built on this platform needs verifying on "
                    "one where it is.",
                )
            )
        if (
            t.coverage
            and t.coverage.missing_mcdc
            and t.status in (Status.VERIFIED, Status.REVIEWED, Status.WEAKLY_VERIFIED)
        ):
            gaps.append(
                Gap(
                    kind="uncovered_condition",
                    req_id=rid,
                    location=", ".join(t.coverage.missing_mcdc[:5]),
                    detail=f"{len(t.coverage.missing_mcdc)} condition(s) in implementing code "
                    "never shown to independently affect their decision (MC/DC)",
                    next_action="Add test cases where only that condition changes and the "
                    "outcome changes with it, or simplify the decision.",
                )
            )
        if t.review and "STALE" in t.review:
            gaps.append(
                Gap(
                    kind="stale_review",
                    req_id=rid,
                    detail=t.review,
                    next_action="Ask a human to re-review: content changed since sign-off.",
                )
            )
    for u in m.unrequired_code:
        gaps.append(
            Gap(
                kind="unrequired_code",
                location=u,
                detail=f"{u} is not linked to any requirement",
                next_action=(
                    "Remove it, link it with `// implements:`, or mark it "
                    "`// derived: <why>` for a human to review."
                    if ctx.cfg.is_cpp
                    else "Remove it, link it with `# implements:`, or mark it "
                    "`# derived: <why>` for a human to review."
                ),
            )
        )
    for d in m.dangling_links:
        gaps.append(
            Gap(
                kind="dangling_link",
                location=d.split(" ")[0],
                detail=d,
                next_action="Fix the requirement id in the annotation.",
            )
        )
    for issue in load_issues(ctx.cfg):
        gaps.append(
            Gap(
                kind="open_issue",
                req_id=issue.req_id,
                detail=f"{issue.id} [{issue.kind}] {issue.description}",
                next_action="A human must resolve the requirement issue.",
            )
        )
    for s in load_suggestions(ctx.cfg):
        if s.status == "unconfirmed":
            stale = item_hash(ctx.cfg, ctx.scan, s.target) != s.content_hash
            gaps.append(
                Gap(
                    kind="stale_suggestion" if stale else "unconfirmed_suggestion",
                    req_id=s.req_id,
                    location=s.target,
                    detail=f"{s.id}: unconfirmed suggestion {s.kind} {s.req_id} -> "
                    f"{s.target}" + (" (target changed since proposed)" if stale else ""),
                    next_action=f"A human should accept or reject: `reqtrace links accept {s.id}`.",
                )
            )
    for f in reqmod.lint(ctx.reqs):
        gaps.append(
            Gap(
                kind="requirement_quality",
                req_id=f.req_id,
                location=f.source,
                detail=f"[{f.severity}] {f.message}",
                next_action="Clarify the requirement, or flag it for a human.",
            )
        )
    for e in ctx.scan.parse_errors:
        gaps.append(
            Gap(
                kind="dangling_link",
                location=e,
                detail=f"Could not parse {e}",
                next_action="Fix the syntax error.",
            )
        )
    return gaps
