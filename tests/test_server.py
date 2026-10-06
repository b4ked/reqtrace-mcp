"""MCP server tests through the official in-memory client (no transport, real protocol)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client, MCPError
from mcp.client import ClientRequestContext
from mcp.types import ElicitRequestParams, ElicitResult

from reqtrace_mcp.server import create_server

EXPECTED_TOOLS = {
    "list_requirements",
    "get_requirement",
    "trace_matrix",
    "find_gaps",
    "impact_of_change",
    "run_verification",
    "coverage_report",
    "lint_requirements",
    "flag_requirement_issue",
    "propose_links",
    "record_review",
    "evidence_report",
}


def _leaves(exc: BaseException) -> list[BaseException]:
    subs = getattr(exc, "exceptions", None)
    return [x for e in subs for x in _leaves(e)] if subs else [exc]


def run(coro_fn: Any) -> Any:
    return anyio.run(coro_fn)


def call(repo: Path, tool: str, args: dict[str, Any] | None = None, **client_kw: Any) -> Any:
    async def go() -> Any:
        async with Client(create_server(repo), **client_kw) as c:
            return await c.call_tool(tool, args or {})

    return run(go)


@pytest.mark.verifies("RT-020")
def test_tool_surface_and_annotations(repo: Path) -> None:
    async def go() -> Any:
        async with Client(create_server(repo)) as c:
            return (await c.list_tools()).tools, c.protocol_version

    tools, proto = run(go)
    assert proto == "2026-07-28"
    by = {t.name: t for t in tools}
    assert set(by) == EXPECTED_TOOLS
    assert by["trace_matrix"].annotations.read_only_hint is True
    assert by["run_verification"].annotations.read_only_hint is False
    assert by["record_review"].meta == {"anthropic/requiresUserInteraction": True}
    for t in tools:
        assert t.output_schema is not None, f"{t.name} has no structured output"
        assert len(t.description or "") > 40, f"{t.name} needs a real description"
    # The reviewer's identity is not a model-supplied argument.
    assert set(by["record_review"].input_schema["properties"]) == {"req_ids", "decision"}


@pytest.mark.verifies("RT-020")
def test_matrix_and_verification_round_trip(repo: Path) -> None:
    r = call(repo, "list_requirements")
    assert not r.is_error
    statuses = {x["id"]: x["status"] for x in r.structured_content["requirements"]}
    assert statuses["ALT-001"] == "NOT_RUN"
    v = call(repo, "run_verification")
    assert not v.is_error, v.content
    assert v.structured_content["outcomes"] == {"passed": 3}
    assert v.structured_content["requirement_status"]["ALT-002"] == "WEAKLY_VERIFIED"
    g = call(repo, "find_gaps")
    assert g.structured_content["clean"] is False
    assert g.structured_content["counts"]["weakly_verified"] == 1


@pytest.mark.verifies("RT-021")
def test_expected_errors_reach_the_model(repo: Path) -> None:
    r = call(repo, "get_requirement", {"req_id": "NOPE-1"})
    assert r.is_error and "Unknown requirement 'NOPE-1'" in r.content[0].text
    r = call(repo, "impact_of_change", {"base_ref": "--output=/tmp/pwned"})
    assert r.is_error and "Invalid git ref" in r.content[0].text
    r = call(repo, "run_verification", {"req_ids": ["ALT-004"]})
    assert r.is_error and "No tests are linked" in r.content[0].text


@pytest.mark.verifies("RT-021")
def test_unexpected_errors_are_sanitised(repo: Path) -> None:
    runs = repo / ".reqtrace" / "runs"
    (runs / "20260101T000000Z-abcdef").mkdir(parents=True)
    (runs / "20260101T000000Z-abcdef" / "run.json").write_text("{not json")
    (runs / "LATEST").write_text("20260101T000000Z-abcdef")
    r = call(repo, "trace_matrix")
    assert r.is_error
    text = r.content[0].text
    assert "Traceback" not in text and "not json" not in text and "validation" not in text.lower()


@pytest.mark.verifies("RT-009")
def test_propose_links_validates_targets(repo: Path) -> None:
    r = call(
        repo,
        "propose_links",
        {
            "links": [
                {
                    "req_id": "ALT-003",
                    "kind": "verifies",
                    "target": "tests/test_core.py::test_alert_at_floor_boundary",
                    "rationale": "x",
                },
                {
                    "req_id": "ALT-003",
                    "kind": "verifies",
                    "target": "/etc/passwd::x",
                    "rationale": "x",
                },
            ]
        },
    )
    sc = r.structured_content
    assert len(sc["accepted_as_unconfirmed"]) == 1
    assert sc["accepted_as_unconfirmed"][0]["status"] == "unconfirmed"
    assert "Unknown target" in sc["rejected"][0]


@pytest.mark.verifies("RT-022")
def test_review_is_recorded_only_with_human_input(repo: Path) -> None:
    asked: list[str] = []

    async def human_accepts(ctx: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        asked.append(params.message)
        return ElicitResult(
            action="accept", content={"reviewer": "A. Human", "rationale": "Checked report"}
        )

    async def human_declines(
        ctx: ClientRequestContext, params: ElicitRequestParams
    ) -> ElicitResult:
        return ElicitResult(action="decline")

    call(repo, "run_verification")
    r = call(
        repo,
        "record_review",
        {"req_ids": ["ALT-001"], "decision": "approved"},
        elicitation_callback=human_declines,
    )
    assert r.structured_content["recorded"] is False
    r = call(
        repo,
        "record_review",
        {"req_ids": ["ALT-001"], "decision": "approved"},
        elicitation_callback=human_accepts,
    )
    assert r.structured_content["recorded"] is True, r
    assert "ALT-001" in asked[0]
    ledger = (repo / ".reqtrace" / "reviews.jsonl").read_text().splitlines()
    assert json.loads(ledger[-1])["reviewer"] == "A. Human"
    s = call(repo, "get_requirement", {"req_id": "ALT-001"})
    assert s.structured_content["status"] == "REVIEWED"


@pytest.mark.verifies("RT-022")
def test_review_without_elicitation_support_records_nothing(repo: Path) -> None:
    # A client that cannot ask a human gets a protocol error (-32021); nothing is recorded.
    # (The in-memory client surfaces it inside an exception group.)
    with pytest.raises(Exception) as info:
        call(repo, "record_review", {"req_ids": ["ALT-001"], "decision": "approved"})
    assert any(isinstance(e, MCPError) and "elicitation" in str(e) for e in _leaves(info.value))
    assert not (repo / ".reqtrace" / "reviews.jsonl").exists()


@pytest.mark.verifies("RT-023")
def test_flag_issue_and_evidence(repo: Path) -> None:
    r = call(
        repo,
        "flag_requirement_issue",
        {"req_id": "ALT-004", "kind": "ambiguous", "description": "Hysteresis start unclear"},
    )
    assert r.structured_content["raised_by"] == "agent"
    e = call(repo, "evidence_report")
    assert e.structured_content["path"] == ".reqtrace/evidence/evidence.md"
    assert "Hysteresis start unclear" in (repo / e.structured_content["path"]).read_text()


@pytest.mark.verifies("RT-020")
def test_resources_and_prompts(repo: Path) -> None:
    async def go() -> Any:
        async with Client(create_server(repo)) as c:
            reqs = await c.read_resource("reqtrace://requirements")
            one = await c.read_resource("reqtrace://requirements/ALT-002")
            ev = await c.read_resource("reqtrace://evidence/latest")
            prompts = (await c.list_prompts()).prompts
            p = await c.get_prompt("implement_traceably", {"req_id": "ALT-004"})
            return reqs, one, ev, prompts, p

    reqs, one, ev, prompts, p = run(go)
    assert len(json.loads(reqs.contents[0].text)) == 4
    assert json.loads(one.contents[0].text)["requirement"]["id"] == "ALT-002"
    assert ev.contents[0].text.startswith("# Verification evidence report")
    assert {x.name for x in prompts} == {"implement_traceably", "independent_review"}
    assert "# implements: ALT-004" in p.messages[0].content.text
