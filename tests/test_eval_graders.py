"""The graders must score known-good and known-bad workspaces correctly before we trust them
with agent output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.grade import grade_run
from evals.tasks import load_task, materialize


@pytest.fixture
def battery(tmp_path: Path):  # type: ignore[no-untyped-def]
    t = load_task("T01-battery-implement")
    ws = tmp_path / "ws"
    base = materialize(t, ws)
    return t, ws, base


@pytest.mark.verifies("EV-001")
def test_untouched_stub_scores_zero(battery) -> None:  # type: ignore[no-untyped-def]
    t, ws, base = battery
    g = grade_run(ws, t, base)
    assert g["task_success"] is False and g["hidden_passed"] == 0
    assert g["verification_strength"] == 0.0 and g["req_coverage"] == 0.0


@pytest.mark.verifies("EV-001")
def test_reference_with_good_tests_scores_full(battery) -> None:  # type: ignore[no-untyped-def]
    t, ws, base = battery
    (ws / t.src_rel).write_text(t.reference)
    (ws / "tests" / "test_bms.py").write_text(t.domain.visible_test)
    g = grade_run(ws, t, base)
    assert g["task_success"] is True and g["hidden_pass_rate"] == 1.0
    assert g["verification_strength"] == 1.0
    assert g["req_coverage"] == 1.0
    assert g["impl_precision"] == 1.0 and g["impl_recall"] == 1.0
    assert g["unrequired_code"] == 0 and g["tests_failing_on_reference"] == 0


@pytest.mark.verifies("EV-002")
def test_weak_tests_lower_strength_not_success(battery) -> None:  # type: ignore[no-untyped-def]
    t, ws, base = battery
    (ws / t.src_rel).write_text(t.reference)
    weak = t.domain.visible_test.replace("assert not cell_fault([4.20, 3.70])\n", "")
    (ws / "tests" / "test_bms.py").write_text(weak)
    g = grade_run(ws, t, base)
    assert g["task_success"] is True  # the code is right...
    assert g["per_req"]["BMS-001"]["traced_detection"] is False  # ...but BMS-001 isn't verified
    assert g["verification_strength"] == pytest.approx(0.8)


@pytest.mark.verifies("EV-002")
def test_untagged_tests_detect_but_do_not_trace(battery) -> None:  # type: ignore[no-untyped-def]
    t, ws, base = battery
    (ws / t.src_rel).write_text(t.reference)
    untagged = "\n".join(
        ln for ln in t.domain.visible_test.splitlines() if "mark.verifies" not in ln
    )
    (ws / "tests" / "test_bms.py").write_text(untagged)
    g = grade_run(ws, t, base)
    assert g["detection_any_test"] == 1.0 and g["verification_strength"] == 0.0
    assert g["req_coverage"] == 0.0


@pytest.mark.verifies("EV-003")
def test_review_grading(tmp_path: Path) -> None:
    t = load_task("T07-thruster-review-boundary")
    ws = tmp_path / "ws"
    base = materialize(t, ws)
    line = next(
        i + 1
        for i, ln in enumerate((ws / t.src_rel).read_text().splitlines())
        if "abs(cmd) <= DEADBAND" in ln
    )
    (ws / "FINDINGS.json").write_text(
        json.dumps(
            [
                {
                    "req_id": "THR-002",
                    "kind": "defect",
                    "file": t.src_rel,
                    "line": line,
                    "description": "2.0 is zeroed",
                },
                {
                    "req_id": "THR-001",
                    "kind": "defect",
                    "file": t.src_rel,
                    "line": 3,
                    "description": "made up",
                },
            ]
        )
    )
    g = grade_run(ws, t, base)
    assert g["defects_found"] == 1 and g["false_positives"] == 1
    assert g["task_success"] is False and g["edited_source"] is False
    (ws / t.src_rel).write_text("# edited\n")
    assert grade_run(ws, t, base)["edited_source"] is True


@pytest.mark.verifies("EV-003")
def test_clean_review_empty_findings_succeeds(tmp_path: Path) -> None:
    t = load_task("T09-battery-review-clean")
    ws = tmp_path / "ws"
    base = materialize(t, ws)
    (ws / "FINDINGS.json").write_text("[]")
    g = grade_run(ws, t, base)
    assert g["task_success"] is True and g["false_positives"] == 0


@pytest.mark.verifies("EV-004")
def test_ambiguity_needs_flag(tmp_path: Path) -> None:
    t = load_task("T10-depth-ambiguity")
    ws = tmp_path / "ws"
    base = materialize(t, ws)
    (ws / t.src_rel).write_text(t.reference)
    g = grade_run(ws, t, base)
    assert g["hidden_pass_rate"] == 1.0 and g["task_success"] is False
    (ws / "FINDINGS.json").write_text(
        json.dumps(
            [
                {
                    "req_id": "DEP-005",
                    "kind": "requirement_issue",
                    "description": "conflicts with DEP-004",
                }
            ]
        )
    )
    assert grade_run(ws, t, base)["task_success"] is True


@pytest.mark.verifies("EV-005")
def test_change_workspace_has_two_commits(tmp_path: Path) -> None:
    import subprocess

    t = load_task("T05-arm-change")
    ws = tmp_path / "ws"
    materialize(t, ws)
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=ws, capture_output=True, text=True
    ).stdout.splitlines()
    assert len(log) == 2
    diff = subprocess.run(
        ["git", "show", "HEAD", "--stat"], cwd=ws, capture_output=True, text=True
    ).stdout
    assert "requirements/arm.yaml" in diff and "src/" not in diff
