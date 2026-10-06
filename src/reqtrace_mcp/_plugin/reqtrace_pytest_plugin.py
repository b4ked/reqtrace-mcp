"""pytest plugin injected by reqtrace into the *target* repo's test run.

Deliberately standard-library only (plus pytest itself and optional coverage), because it is
imported inside the target repo's own environment, not reqtrace's.

It does three things:
  * registers the `verifies` marker so tests don't warn about an unknown mark;
  * switches coverage.py's dynamic context to the test's node id while each test runs,
    so we can later ask "which lines did *this* test execute?";
  * writes each test's outcome and `verifies` ids to the JSON file in REQTRACE_RESULTS
    (JUnit XML does not carry markers).
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

_results: dict[str, dict[str, Any]] = {}
_marks: dict[str, list[str]] = {}


def _coverage() -> Any:
    try:
        import coverage
    except ImportError:
        return None
    return coverage.Coverage.current()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "verifies(*req_ids): requirements this test verifies")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Any:
    ids: list[str] = []
    for mark in item.iter_markers(name="verifies"):
        ids.extend(str(a) for a in mark.args)
    _marks[item.nodeid] = list(dict.fromkeys(ids))
    cov = _coverage()
    if cov is not None:
        cov.switch_context(item.nodeid)
    yield
    if cov is not None:
        cov.switch_context("")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    rec = _results.setdefault(
        report.nodeid, {"outcome": "passed", "duration_s": 0.0, "message": ""}
    )
    rec["duration_s"] += float(getattr(report, "duration", 0.0) or 0.0)
    if report.when == "call":
        if report.passed:
            rec["outcome"] = "passed" if rec["outcome"] == "passed" else rec["outcome"]
        elif report.skipped:
            rec["outcome"] = "skipped"
        else:
            rec["outcome"] = "failed"
            rec["message"] = str(report.longreprtext)[-2000:]
    elif report.failed:  # setup or teardown failure
        rec["outcome"] = "error"
        rec["message"] = str(report.longreprtext)[-2000:]
    elif report.skipped and report.when == "setup":
        rec["outcome"] = "skipped"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    out = os.environ.get("REQTRACE_RESULTS")
    if not out:
        return
    tests = [
        {"nodeid": nid, "verifies": _marks.get(nid, []), **rec} for nid, rec in _results.items()
    ]
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"exitstatus": int(exitstatus), "tests": tests}, fh, indent=1)
