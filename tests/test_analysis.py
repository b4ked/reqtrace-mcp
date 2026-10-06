from __future__ import annotations

from pathlib import Path

import pytest

from reqtrace_mcp.cli import main as cli
from reqtrace_mcp.core.analysis import build_matrix, find_gaps, load_context
from reqtrace_mcp.core.config import Config
from reqtrace_mcp.core.impact import impact_of_change
from reqtrace_mcp.core.model import Status
from reqtrace_mcp.core.report import write_evidence
from reqtrace_mcp.core.runner import run_tests
from reqtrace_mcp.core.state import add_suggestion, record_review, set_suggestion_status

from .conftest import git


def statuses(cfg: Config) -> dict[str, Status]:
    return {t.requirement.id: t.status for t in build_matrix(load_context(cfg)).requirements}


@pytest.mark.verifies("RT-004")
def test_statuses_before_and_after_run(cfg: Config) -> None:
    assert statuses(cfg) == {
        "ALT-001": Status.NOT_RUN,
        "ALT-002": Status.NOT_RUN,
        "ALT-003": Status.NOT_VERIFIED,
        "ALT-004": Status.NOT_IMPLEMENTED,
    }
    run = run_tests(cfg)
    assert {t.outcome for t in run.tests} == {"passed"}
    assert len(run.tests) == 3  # two parametrised cases + one test
    assert statuses(cfg) == {
        "ALT-001": Status.VERIFIED,
        "ALT-002": Status.WEAKLY_VERIFIED,
        "ALT-003": Status.NOT_VERIFIED,
        "ALT-004": Status.NOT_IMPLEMENTED,
    }


@pytest.mark.verifies("RT-005")
def test_runtime_records_verifies_markers(cfg: Config) -> None:
    run = run_tests(cfg)
    marks = {t.nodeid: t.verifies for t in run.tests}
    assert marks["tests/test_core.py::test_alert_at_floor_boundary[499-True]"] == ["ALT-001"]


@pytest.mark.verifies("RT-004")
def test_failing_test_makes_requirement_failing(cfg: Config, repo: Path) -> None:
    core = repo / "src/alerter/core.py"
    core.write_text(core.read_text().replace("alt_ft < validate_floor", "alt_ft <= validate_floor"))
    run_tests(cfg)
    assert statuses(cfg)["ALT-001"] == Status.FAILING
    gaps = find_gaps(load_context(cfg))
    failing = [g for g in gaps if g.kind == "failing"]
    assert failing and "500-False" in failing[0].detail


@pytest.mark.verifies("RT-006")
def test_coverage_figures_and_uncovered_branch(cfg: Config) -> None:
    run_tests(cfg)
    m = build_matrix(load_context(cfg))
    alt1 = next(t for t in m.requirements if t.requirement.id == "ALT-001")
    assert alt1.coverage and alt1.coverage.branches == 2 and alt1.coverage.branches_covered == 1
    assert any(
        g.kind == "uncovered_branch" and g.req_id == "ALT-001"
        for g in find_gaps(load_context(cfg), m)
    )


@pytest.mark.verifies("RT-007")
def test_unrequired_code_and_derived(cfg: Config, repo: Path) -> None:
    ctx = load_context(cfg)
    assert build_matrix(ctx).unrequired_code == ["src/alerter/core.py::altitude_in_metres"]
    core = repo / "src/alerter/core.py"
    core.write_text(
        core.read_text().replace(
            "def altitude_in_metres", "# derived: display units helper\ndef altitude_in_metres"
        )
    )
    assert build_matrix(load_context(cfg)).unrequired_code == []


@pytest.mark.verifies("RT-008")
def test_review_goes_stale_when_code_changes(cfg: Config, repo: Path) -> None:
    run_tests(cfg)
    ctx = load_context(cfg)
    req = next(r for r in ctx.reqs if r.id == "ALT-001")
    record_review(cfg, req, ctx.scan, "approved", "Reviewer", "Checked boundaries")
    assert statuses(cfg)["ALT-001"] == Status.REVIEWED
    core = repo / "src/alerter/core.py"
    core.write_text(core.read_text().replace("return True\n", "return True  # fail safe\n", 1))
    ctx = load_context(cfg)
    assert ctx.results_stale
    kinds = {g.kind for g in find_gaps(ctx)}
    assert {"stale_review", "not_run"} <= kinds
    assert statuses(cfg)["ALT-001"] == Status.VERIFIED


@pytest.mark.verifies("RT-008")
def test_review_requires_name_and_rationale(cfg: Config) -> None:
    ctx = load_context(cfg)
    from reqtrace_mcp.core.config import ReqtraceError

    with pytest.raises(ReqtraceError):
        record_review(cfg, ctx.reqs[0], ctx.scan, "approved", " ", "x")


@pytest.mark.verifies("RT-009")
def test_suggestions_unconfirmed_until_accepted(cfg: Config) -> None:
    ctx = load_context(cfg)
    s = add_suggestion(
        cfg,
        ctx.scan,
        "ALT-003",
        "verifies",
        "tests/test_core.py::test_alert_at_floor_boundary",
        "covers fail-safe?",
    )
    assert statuses(cfg)["ALT-003"] == Status.NOT_VERIFIED
    assert any(g.kind == "unconfirmed_suggestion" for g in find_gaps(load_context(cfg)))
    set_suggestion_status(cfg, s.id, "accepted")
    assert statuses(cfg)["ALT-003"] == Status.NOT_RUN


@pytest.mark.verifies("RT-011")
def test_impact_of_code_test_and_requirement_changes(cfg: Config, repo: Path) -> None:
    core = repo / "src/alerter/core.py"
    core.write_text(
        core.read_text().replace('raise ValueError(f"floor', 'raise ValueError(f"Floor')
    )
    reqs = repo / "requirements/alerter.yaml"
    reqs.write_text(
        reqs.read_text().replace("exceeds the floor by 50 ft", "exceeds the floor by 60 ft")
    )
    res = impact_of_change(load_context(cfg))
    assert set(res.affected_requirements) == {"ALT-002", "ALT-004"}
    assert "tests/test_core.py::test_floor_limits" in res.tests_to_rerun
    assert res.changed_items == ["src/alerter/core.py::validate_floor"]


@pytest.mark.verifies("RT-011")
def test_impact_of_deleted_function(cfg: Config, repo: Path) -> None:
    core = repo / "src/alerter/core.py"
    text = core.read_text()
    start = text.index("# implements: ALT-002")
    end = text.index("# implements: ALT-001")
    core.write_text(text[:start] + text[end:])
    res = impact_of_change(load_context(cfg))
    assert "ALT-002" in res.affected_requirements


@pytest.mark.verifies("RT-011")
def test_impact_committed_only_and_bad_ref(cfg: Config, repo: Path) -> None:
    (repo / "src/alerter/core.py").write_text("# implements: ALT-001\ndef x(): pass\n")
    res = impact_of_change(load_context(cfg), "HEAD", include_uncommitted=False)
    assert res.affected_requirements == {}
    from reqtrace_mcp.core.config import ReqtraceError

    with pytest.raises(ReqtraceError, match="Invalid git ref"):
        impact_of_change(load_context(cfg), "--output=/tmp/x")
    with pytest.raises(ReqtraceError):
        impact_of_change(load_context(cfg), "no-such-branch")
    git(repo, "status")


@pytest.mark.verifies("RT-012")
def test_evidence_report(cfg: Config) -> None:
    run_tests(cfg)
    path, m, gaps = write_evidence(load_context(cfg))
    text = path.read_text()
    assert "**1 of 4 requirements verified**" in text
    assert "WEAKLY_VERIFIED" in text and "altitude_in_metres" in text
    assert "not a qualified tool" in text
    assert (path.parent / "matrix.json").exists()


@pytest.mark.verifies("RT-013")
def test_gate_exit_codes(repo: Path) -> None:
    root = ["--root", str(repo)]
    assert cli([*root, "verify"]) == 0
    assert cli([*root, "gate"]) == 1
    (repo / ".reqtrace.yaml").write_text(
        "source_dirs: [src]\npytest_args: ['--import-mode=importlib']\n"
        "gate: {max_unimplemented: 1, max_untested: 1, max_weakly_verified: 1, "
        "max_unrequired: 1}\n"
    )
    assert cli([*root, "gate"]) == 0


def test_cli_reports_errors_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(["--root", str(tmp_path), "matrix"]) == 2
    assert "No requirements found" in capsys.readouterr().err
