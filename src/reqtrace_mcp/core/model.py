"""Data model shared by the core library, CLI and MCP server."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Requirement(BaseModel):
    id: str
    title: str = ""
    text: str
    rationale: str = ""
    acceptance: list[str] = Field(default_factory=list)
    parent: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: str = Field(default="", description="File and line the requirement was loaded from")


class CodeItem(BaseModel):
    """A function, method or class found in a source or test file."""

    id: str = Field(description="path::qualname, path relative to the repo root")
    path: str
    qualname: str
    kind: Literal["function", "method", "class"]
    start_line: int = Field(description="First line including decorators")
    def_line: int
    body_start: int = Field(description="First line of the body")
    end_line: int
    implements: list[str] = Field(default_factory=list)
    verifies: list[str] = Field(default_factory=list)
    derived: str | None = Field(default=None, description="Rationale if marked derived")


LinkSource = Literal["annotation", "accepted_suggestion"]


class Link(BaseModel):
    req_id: str
    kind: Literal["implements", "verifies"]
    target: str = Field(description="CodeItem id (path::qualname)")
    source: LinkSource = "annotation"
    location: str = Field(description="path:line of the annotation")


class TestOutcome(BaseModel):
    __test__ = False  # not a pytest test class

    nodeid: str
    outcome: Literal["passed", "failed", "skipped", "error"]
    duration_s: float = 0.0
    verifies: list[str] = Field(default_factory=list)
    message: str = ""


class RunSummary(BaseModel):
    run_id: str
    started_at: str
    duration_s: float
    exit_code: int
    command: list[str]
    tests: list[TestOutcome]
    timed_out: bool = False
    stderr_tail: str = ""


class Status(str, Enum):
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_RUN = "NOT_RUN"
    FAILING = "FAILING"
    WEAKLY_VERIFIED = "WEAKLY_VERIFIED"
    VERIFIED = "VERIFIED"
    REVIEWED = "REVIEWED"


class CoverageFigures(BaseModel):
    statements: int = 0
    statements_covered: int = 0
    branches: int = 0
    branches_covered: int = 0
    missing_lines: list[str] = Field(default_factory=list, description="path:line")
    missing_branches: list[str] = Field(default_factory=list, description="path:from->to")

    @property
    def statement_pct(self) -> float | None:
        return None if not self.statements else 100.0 * self.statements_covered / self.statements

    @property
    def branch_pct(self) -> float | None:
        return None if not self.branches else 100.0 * self.branches_covered / self.branches


class RequirementTrace(BaseModel):
    requirement: Requirement
    status: Status
    implemented_by: list[str]
    verified_by: list[str]
    test_results: dict[str, str] = Field(description="nodeid -> outcome, latest run")
    tests_exercising_code: list[str] = Field(
        default_factory=list, description="Linked tests that executed implementing code"
    )
    coverage: CoverageFigures | None = None
    review: str | None = Field(default=None, description="Latest review decision, if current")
    open_issues: int = 0


class Matrix(BaseModel):
    generated_at: str
    run_id: str | None
    requirements: list[RequirementTrace]
    unrequired_code: list[str]
    dangling_links: list[str]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {s.value: 0 for s in Status}
        for r in self.requirements:
            out[r.status.value] += 1
        return out


GapKind = Literal[
    "unimplemented",
    "untested",
    "not_run",
    "failing",
    "weakly_verified",
    "unrequired_code",
    "dangling_link",
    "stale_review",
    "stale_suggestion",
    "unconfirmed_suggestion",
    "uncovered_branch",
    "open_issue",
    "requirement_quality",
]


class Gap(BaseModel):
    kind: GapKind
    req_id: str | None = None
    location: str | None = None
    detail: str
    next_action: str


class LintFinding(BaseModel):
    req_id: str | None
    severity: Literal["error", "warning"]
    message: str
    source: str = ""


class Review(BaseModel):
    req_id: str
    decision: Literal["approved", "rejected"]
    reviewer: str
    rationale: str
    timestamp: str
    content_hash: str


class Issue(BaseModel):
    id: str
    req_id: str
    kind: Literal["ambiguous", "conflict", "untestable", "incomplete", "other"]
    description: str
    raised_by: str
    timestamp: str
    related: list[str] = Field(default_factory=list)


class Suggestion(BaseModel):
    id: str
    req_id: str
    kind: Literal["implements", "verifies"]
    target: str
    rationale: str
    proposed_at: str
    content_hash: str
    status: Literal["unconfirmed", "accepted", "rejected"] = "unconfirmed"


class ImpactResult(BaseModel):
    base_ref: str
    include_uncommitted: bool
    changed_files: list[str]
    changed_items: list[str] = Field(description="Functions/classes/tests touched by the diff")
    affected_requirements: dict[str, list[str]] = Field(description="req id -> reasons")
    tests_to_rerun: list[str]
    reviews_invalidated: list[str]
