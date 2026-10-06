"""MCP server exposing reqtrace to coding agents (stdio).

Design notes (see docs/DECISIONS.md):
* Deterministic: the server never calls an LLM. It computes facts; the agent reasons.
* Stateless per call: every tool reloads from disk, matching the stateless 2026-07-28 protocol.
  Persistent state lives in the repo under `.reqtrace/`.
* Only `ToolError` messages reach the model; anything unexpected is logged to stderr.
* `record_review` is human-only: Claude Code must prompt on every call
  (`anthropic/requiresUserInteraction`), and the reviewer's identity and rationale are
  collected from the human by elicitation, never from tool arguments.
"""

from __future__ import annotations

import argparse
import functools
import logging
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, ParamSpec, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver import (
    AcceptedElicitation,
    Elicit,
    ElicitationResult,
    Resolve,
)
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import __version__
from .core import requirements as reqmod
from .core.analysis import Context, build_matrix, find_gaps, load_context, verifying_tests
from .core.config import Config, ReqtraceError, find_root, load_config
from .core.impact import impact_of_change as _impact
from .core.model import (
    Gap,
    ImpactResult,
    Issue,
    LintFinding,
    Matrix,
    RequirementTrace,
    Status,
    Suggestion,
)
from .core.report import render_markdown, write_evidence
from .core.runner import run_tests
from .core.state import add_suggestion, flag_issue
from .core.state import record_review as _record_review

log = logging.getLogger("reqtrace")
P = ParamSpec("P")
R = TypeVar("R")

INSTRUCTIONS = """\
reqtrace makes your work on this repository traceable and verifiable.
Requirements live in YAML (see list_requirements). Python: link code with a comment
`# implements: REQ-ID` directly above the function, and tests with
`@pytest.mark.verifies("REQ-ID")`. C/C++: `// implements: REQ-ID` above the function and
`// verifies: REQ-ID` above the TEST(...) or test main.
Workflow: lint_requirements -> flag unclear requirements with flag_requirement_issue
instead of guessing -> implement with annotations -> write tests for every acceptance
criterion -> run_verification -> find_gaps until clean -> evidence_report.
A requirement is only VERIFIED when a linked test passes AND executes the implementing code.
You cannot sign off your own work: record_review asks a human.
"""

RO = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
WRITES_STATE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)


# ------------------------------------------------------------------ results ---


class RequirementSummary(BaseModel):
    id: str
    title: str
    status: Status
    text: str
    acceptance: list[str]


class RequirementList(BaseModel):
    requirements: list[RequirementSummary]
    counts: dict[str, int]


class GapList(BaseModel):
    gaps: list[Gap]
    counts: dict[str, int]
    clean: bool = Field(description="True when no blocking gaps remain")


class VerificationResult(BaseModel):
    run_id: str
    duration_s: float
    timed_out: bool
    outcomes: dict[str, int]
    failed_tests: list[str]
    requirement_status: dict[str, Status]
    output_tail: str = Field(description="Tail of test output, for diagnosing errors")


class CoverageResult(BaseModel):
    run_id: str | None
    requirements: list[RequirementTrace]


class SuggestionResult(BaseModel):
    accepted_as_unconfirmed: list[Suggestion]
    rejected: list[str]


class ProposedLink(BaseModel):
    req_id: str
    kind: Literal["implements", "verifies"]
    target: str = Field(
        description="path::qualname, e.g. src/pkg/mod.py::func or "
        "tests/test_mod.py::TestClass.test_x"
    )
    rationale: str


class ReviewResult(BaseModel):
    recorded: bool
    detail: str


class EvidenceResult(BaseModel):
    path: str
    counts: dict[str, int]
    open_gaps: int
    unrequired_code: int


class ReviewerInput(BaseModel):
    reviewer: str = Field(description="Your name (the human reviewer)")
    rationale: str = Field(description="What you checked and why you are satisfied (or not)")


async def ask_reviewer(
    req_ids: list[str], decision: Literal["approved", "rejected"]
) -> Elicit[ReviewerInput]:
    """Resolver: the reviewer's identity and rationale come from the human, not the model."""
    return Elicit(
        f"Human sign-off requested: mark {', '.join(req_ids)} as {decision.upper()}. "
        "Only continue if you (a human) have checked the evidence report. "
        "Enter your name and rationale, or decline.",
        ReviewerInput,
    )


BLOCKING = {
    "unimplemented",
    "untested",
    "not_run",
    "failing",
    "weakly_verified",
    "unrequired_code",
    "dangling_link",
}


def create_server(root: str | Path | None = None) -> MCPServer:
    mcp = MCPServer("reqtrace", instructions=INSTRUCTIONS, version=__version__)

    def cfg() -> Config:
        return load_config(find_root(root))

    def ctx() -> Context:
        return load_context(cfg())

    def tool_errors(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return fn(*args, **kwargs)
            except ReqtraceError as exc:
                raise ToolError(str(exc)) from exc

        return wrapper

    def atool_errors(fn: Callable[P, Any]) -> Callable[P, Any]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            try:
                return await fn(*args, **kwargs)
            except ReqtraceError as exc:
                raise ToolError(str(exc)) from exc

        return wrapper

    def known_req(c: Context, req_id: str) -> None:
        if req_id not in {r.id for r in c.reqs}:
            raise ReqtraceError(
                f"Unknown requirement {req_id!r}. Known: {', '.join(r.id for r in c.reqs)}"
            )

    # ---------------------------------------------------------------- tools ---

    @mcp.tool(annotations=RO)
    @tool_errors
    def list_requirements(tag: str | None = None, status: Status | None = None) -> RequirementList:
        """List requirements with their current verification status."""
        m = build_matrix(ctx())
        rows = [
            RequirementSummary(
                id=t.requirement.id,
                title=t.requirement.title,
                status=t.status,
                text=t.requirement.text,
                acceptance=t.requirement.acceptance,
            )
            for t in m.requirements
            if (tag is None or tag in t.requirement.tags) and (status is None or t.status == status)
        ]
        return RequirementList(requirements=rows, counts=m.counts())

    @mcp.tool(annotations=RO)
    @tool_errors
    def get_requirement(req_id: str) -> RequirementTrace:
        """One requirement with its implementing code, linked tests, latest results, coverage,
        review state and number of open issues."""
        c = ctx()
        known_req(c, req_id)
        return next(t for t in build_matrix(c).requirements if t.requirement.id == req_id)

    @mcp.tool(annotations=RO)
    @tool_errors
    def trace_matrix() -> Matrix:
        """Full trace matrix: requirement -> code -> tests -> latest results, plus code that no
        requirement asked for and annotations that name unknown requirements."""
        return build_matrix(ctx())

    @mcp.tool(annotations=RO)
    @tool_errors
    def find_gaps(kinds: list[str] | None = None) -> GapList:
        """Everything standing between this repo and verified, signed-off requirements, each
        with a suggested next action. `clean` is true when no blocking gaps remain."""
        gaps = find_gaps_core(ctx())
        if kinds:
            gaps = [g for g in gaps if g.kind in kinds]
        counts: Counter[str] = Counter(str(g.kind) for g in gaps)
        return GapList(
            gaps=gaps, counts=dict(counts), clean=not any(g.kind in BLOCKING for g in gaps)
        )

    @mcp.tool(annotations=RO)
    @tool_errors
    def impact_of_change(base_ref: str = "HEAD", include_uncommitted: bool = True) -> ImpactResult:
        """Requirements and tests affected by changes since `base_ref` (a git ref), including
        requirement text edits and deleted functions. Lists tests to re-run and reviews that
        the change invalidates."""
        return _impact(ctx(), base_ref, include_uncommitted)

    @mcp.tool(annotations=WRITES_STATE)
    @tool_errors
    def run_verification(req_ids: list[str] | None = None) -> VerificationResult:
        """Run the repo's tests under coverage and map results to requirements. Python:
        pytest with per-test contexts. C/C++: builds with clang coverage (and MC/DC) using the
        build commands in .reqtrace.yaml, then runs each test in its own process. With
        `req_ids`, runs only tests linked to those requirements. The commands come from the
        repo's config, never from arguments."""
        c = ctx()
        nodes = None
        if req_ids:
            for r in req_ids:
                known_req(c, r)
            nodes = sorted({n for r in req_ids for n in verifying_tests(c, r)})
            if not nodes:
                raise ReqtraceError(f"No tests are linked to {', '.join(req_ids)} yet")
        run = run_tests(c.cfg, nodes)
        m = build_matrix(load_context(c.cfg))
        return VerificationResult(
            run_id=run.run_id,
            duration_s=run.duration_s,
            timed_out=run.timed_out,
            outcomes=dict(Counter(t.outcome for t in run.tests)),
            failed_tests=[t.nodeid for t in run.tests if t.outcome in ("failed", "error")],
            requirement_status={t.requirement.id: t.status for t in m.requirements},
            output_tail=run.stderr_tail[-600:],
        )

    @mcp.tool(annotations=RO)
    @tool_errors
    def coverage_report(req_id: str | None = None) -> CoverageResult:
        """Statement and branch coverage (plus MC/DC for C/C++ with clang >= 18) of each
        requirement's implementing code from the latest run, with uncovered lines, branches
        and conditions, and implementing code that no linked test executes."""
        c = ctx()
        if req_id:
            known_req(c, req_id)
        m = build_matrix(c)
        rows = [t for t in m.requirements if req_id is None or t.requirement.id == req_id]
        return CoverageResult(run_id=m.run_id, requirements=rows)

    @mcp.tool(annotations=RO)
    @tool_errors
    def lint_requirements() -> list[LintFinding]:
        """Deterministic requirement quality checks (missing acceptance criteria, vague words,
        compound requirements). Judging ambiguity and conflicts is your job: use
        flag_requirement_issue."""
        return reqmod.lint(reqmod.load_requirements(cfg()))

    @mcp.tool(annotations=WRITES_STATE)
    @tool_errors
    def flag_requirement_issue(
        req_id: str,
        kind: Literal["ambiguous", "conflict", "untestable", "incomplete", "other"],
        description: str,
        related_req_ids: list[str] | None = None,
    ) -> Issue:
        """Record a problem with a requirement for a human to resolve. Use this instead of
        guessing when a requirement is ambiguous, conflicts with another, or can't be tested."""
        c = ctx()
        known_req(c, req_id)
        for r in related_req_ids or []:
            known_req(c, r)
        return flag_issue(
            c.cfg, req_id, kind, description, raised_by="agent", related=related_req_ids
        )

    @mcp.tool(annotations=WRITES_STATE)
    @tool_errors
    def propose_links(links: list[ProposedLink]) -> SuggestionResult:
        """Suggest trace links you believe exist but are not annotated. They are stored as
        UNCONFIRMED and do not count until a human accepts them. Prefer adding annotations."""
        c = ctx()
        ok: list[Suggestion] = []
        bad: list[str] = []
        for lk in links:
            try:
                known_req(c, lk.req_id)
                ok.append(
                    add_suggestion(c.cfg, c.scan, lk.req_id, lk.kind, lk.target, lk.rationale)
                )
            except ReqtraceError as exc:
                bad.append(f"{lk.req_id} -> {lk.target}: {exc}")
        return SuggestionResult(accepted_as_unconfirmed=ok, rejected=bad)

    @mcp.tool(
        annotations=WRITES_STATE,
        meta={"anthropic/requiresUserInteraction": True},
    )
    @atool_errors
    async def record_review(
        req_ids: list[str],
        decision: Literal["approved", "rejected"],
        reviewer_input: Annotated[ElicitationResult[ReviewerInput], Resolve(ask_reviewer)],
    ) -> ReviewResult:
        """Ask a HUMAN to sign off requirements. The human is prompted for their name and
        rationale; you cannot supply them. If no human answers, nothing is recorded."""
        if not isinstance(reviewer_input, AcceptedElicitation):
            return ReviewResult(recorded=False, detail="The human declined; no review recorded.")
        c = ctx()
        reqs = {r.id: r for r in c.reqs}
        for r in req_ids:
            known_req(c, r)
        recorded = [
            _record_review(
                c.cfg,
                reqs[r],
                c.scan,
                decision,
                reviewer_input.data.reviewer,
                reviewer_input.data.rationale,
                c.extra_links,
            )
            for r in req_ids
        ]
        return ReviewResult(
            recorded=True,
            detail="; ".join(
                f"{rv.req_id} {rv.decision} by {rv.reviewer} (hash {rv.content_hash})"
                for rv in recorded
            ),
        )

    @mcp.tool(annotations=WRITES_STATE)
    @tool_errors
    def evidence_report() -> EvidenceResult:
        """Write the evidence pack (Markdown + matrix JSON) to .reqtrace/evidence/ for a human
        to review. Run run_verification first so results are current."""
        path, m, gaps = write_evidence(ctx())
        return EvidenceResult(
            path=str(path.relative_to(cfg().root)),
            counts=m.counts(),
            open_gaps=len(gaps),
            unrequired_code=len(m.unrequired_code),
        )

    # ------------------------------------------------------------ resources ---

    @mcp.resource("reqtrace://requirements", mime_type="application/json")
    def requirements_resource() -> str:
        """All requirements as JSON."""
        reqs = reqmod.load_requirements(cfg())
        return "[" + ",".join(r.model_dump_json() for r in reqs) + "]"

    @mcp.resource("reqtrace://requirements/{req_id}", mime_type="application/json")
    def requirement_resource(req_id: str) -> str:
        """One requirement's trace as JSON."""
        c = ctx()
        for t in build_matrix(c).requirements:
            if t.requirement.id == req_id:
                return t.model_dump_json(indent=1)
        raise ToolError(f"Unknown requirement {req_id}")

    @mcp.resource("reqtrace://matrix", mime_type="application/json")
    def matrix_resource() -> str:
        """The current trace matrix as JSON."""
        return build_matrix(ctx()).model_dump_json(indent=1)

    @mcp.resource("reqtrace://evidence/latest", mime_type="text/markdown")
    def evidence_resource() -> str:
        """The evidence report, rendered from current state."""
        return render_markdown(ctx())

    # -------------------------------------------------------------- prompts ---

    @mcp.prompt()
    def implement_traceably(req_id: str) -> str:
        """Implement one requirement with full traceability and evidence."""
        return (
            f"Implement requirement {req_id} traceably using the reqtrace tools.\n"
            f"1. get_requirement {req_id} and lint_requirements. If it is ambiguous, conflicts "
            "with another requirement, or is untestable, call flag_requirement_issue and stop "
            "for a human instead of guessing.\n"
            f"2. Implement it. Put `# implements: {req_id}` (`// implements: {req_id}` in C/C++) "
            "directly above each function that implements it. Add nothing the requirement "
            "does not ask for.\n"
            f'3. Write tests marked `@pytest.mark.verifies("{req_id}")` (C/C++: a '
            f"`// verifies: {req_id}` comment above the TEST) covering every "
            "acceptance criterion, including both sides of each boundary.\n"
            "4. run_verification, then find_gaps. Fix failing, weakly_verified, "
            "uncovered_branch, uncovered_condition, unexercised_code and unrequired_code "
            "gaps. Never weaken a test to make it pass.\n"
            "5. evidence_report, then ask the human to review it. Do not call record_review "
            "yourself unless the human asks you to start the sign-off."
        )

    @mcp.prompt()
    def independent_review(req_ids: str) -> str:
        """Independent verification review of requirements (comma-separated ids)."""
        return (
            f"Perform an independent verification review of {req_ids}. You did not write this "
            "code: judge it only against the requirement text and acceptance criteria, not "
            "against comments or the implementer's explanation.\n"
            "For each requirement: read it (get_requirement), read the implementing code and "
            "the linked tests, run_verification, and check coverage_report.\n"
            "Report findings as a list of {req_id, kind, file, line, description}, where kind "
            "is one of: defect, missing_requirement, untested_behaviour, weak_test, "
            "unrequired_code, requirement_issue. Do not edit any files. If you find nothing, "
            "say so explicitly rather than inventing findings."
        )

    return mcp


def find_gaps_core(c: Context) -> list[Gap]:
    return find_gaps(c)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="reqtrace-mcp", description="reqtrace MCP server (stdio)")
    p.add_argument("--root", help="Repository root (default: $CLAUDE_PROJECT_DIR or cwd)")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="reqtrace %(levelname)s %(message)s"
    )
    try:
        root = find_root(args.root)
    except ReqtraceError as exc:
        print(f"reqtrace-mcp: {exc}", file=sys.stderr)
        sys.exit(2)
    log.info("serving %s", root)
    create_server(root).run("stdio")


if __name__ == "__main__":
    main()
