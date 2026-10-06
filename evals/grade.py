"""Deterministic graders. They never trust the agent's claims: everything is re-derived from the
final workspace, the hidden tests, the reference implementation and the mutants."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from reqtrace_mcp.core import requirements as reqmod
from reqtrace_mcp.core.analysis import build_matrix, load_context
from reqtrace_mcp.core.annotations import scan_text
from reqtrace_mcp.core.config import Config
from reqtrace_mcp.core.runner import PARAM_RE, PLUGIN_DIR, run_tests, target_env

from .tasks import PYTEST_INI, Task, defect_lines

DEFECT_KINDS = {"defect", "missing_requirement", "unrequired_code"}


def _copy_ws(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        ".git", ".reqtrace", "__pycache__", ".pytest_cache", ".coverage"))
    (dst / ".grader_pytest.ini").write_text(PYTEST_INI)


def run_pytest(root: Path, test_path: str, timeout: int = 180) -> dict[str, dict[str, Any]]:
    """Run pytest on `test_path` inside `root`; return nodeid -> {outcome, verifies}."""
    results = root / ".grader_results.json"
    results.unlink(missing_ok=True)
    env = target_env()
    env["PYTHONPATH"] = str(PLUGIN_DIR)
    env["REQTRACE_RESULTS"] = str(results)
    env.pop("PYTEST_ADDOPTS", None)
    # Mutants differ by a character or two and are written within the same second: a cached
    # .pyc keyed on (mtime, size) would silently run the previous mutant. Never cache bytecode.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = ["python3", "-m", "pytest", test_path, "-p", "reqtrace_pytest_plugin",
           "-p", "no:cacheprovider", "-q", "-c", str(root / ".grader_pytest.ini"),
           f"--rootdir={root}"]
    try:
        subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {}
    if not results.exists():
        return {}
    data = json.loads(results.read_text())
    return {t["nodeid"]: {"outcome": t["outcome"], "verifies": t.get("verifies", [])}
            for t in data.get("tests", [])}


def _overlay(ws: Path, t: Task, source: str | None, tmp: Path, name: str) -> Path:
    d = tmp / name
    _copy_ws(ws, d)
    if source is not None:
        (d / t.src_rel).parent.mkdir(parents=True, exist_ok=True)
        (d / t.src_rel).write_text(source)
    return d


def grade_hidden(ws: Path, t: Task, tmp: Path) -> dict[str, Any]:
    d = _overlay(ws, t, None, tmp, "hidden")
    (d / "hidden_tests").mkdir()
    (d / "hidden_tests" / "test_hidden.py").write_text(t.hidden_test)
    res = run_pytest(d, "hidden_tests")
    res = {k: v for k, v in res.items() if not set(v["verifies"]) & set(t.drop_reqs)}
    passed = sum(1 for v in res.values() if v["outcome"] == "passed")
    per_req: dict[str, bool] = {}
    for v in res.values():
        for r in v["verifies"]:
            per_req[r] = per_req.get(r, True) and v["outcome"] == "passed"
    return {"hidden_total": len(res), "hidden_passed": passed,
            "hidden_pass_rate": passed / len(res) if res else 0.0,
            "task_success": bool(res) and passed == len(res),
            "hidden_per_req": per_req}


def grade_strength(ws: Path, t: Task, tmp: Path) -> dict[str, Any]:
    """Run the AGENT's tests against the reference and each one-requirement mutant."""
    ref = run_pytest(_overlay(ws, t, t.reference, tmp, "ref"), "tests")
    if not ref:
        return {"agent_tests": 0, "verification_strength": 0.0, "detection_any_test": 0.0,
                "link_precision": None, "tests_failing_on_reference": 0, "per_req": {}}
    base = lambda n: PARAM_RE.sub("", n)  # noqa: E731
    portable = {n for n, v in ref.items() if v["outcome"] == "passed"}
    # Tests of requirements excluded from grading (e.g. the conflicting pair in an ambiguity
    # task) have no correct answer, so failing on the reference says nothing about them.
    failing_ref = sorted({base(n) for n, v in ref.items() if v["outcome"] in ("failed", "error")
                          and not set(v["verifies"]) & set(t.drop_reqs)})
    per_req: dict[str, dict[str, bool]] = {}
    kills: dict[str, set[str]] = {}
    for rid, src in sorted(t.mutant_sources.items()):
        mut = run_pytest(_overlay(ws, t, src, tmp, f"mut_{rid}"), "tests")
        kills[rid] = {n for n in portable if mut.get(n, {}).get("outcome") != "passed"}
        linked = {n for n in portable if rid in ref[n]["verifies"]}
        per_req[rid] = {"traced_detection": bool(kills[rid] & linked),
                        "any_detection": bool(kills[rid]), "linked_tests": bool(linked)}
    # Link precision: of (test, req) links on portable tests, how many detect that req's mutant.
    links = [(n, rid) for n in portable for rid in ref[n]["verifies"] if rid in kills]
    link_hits = sum(n in kills[rid] for n, rid in links)
    link_total = len(links)
    reqs = list(per_req)
    return {
        "agent_tests": len(ref), "portable_tests": len(portable),
        "tests_failing_on_reference": len(failing_ref),
        "tests_failing_on_reference_ids": failing_ref,
        "verification_strength": sum(per_req[r]["traced_detection"] for r in reqs) / len(reqs),
        "detection_any_test": sum(per_req[r]["any_detection"] for r in reqs) / len(reqs),
        "link_precision": link_hits / link_total if link_total else None,
        "per_req": per_req,
    }


def _top(qual: str) -> str:
    return qual.split(".")[0]


def grade_trace(ws: Path, t: Task, tmp: Path) -> dict[str, Any]:
    """Implements-link precision/recall vs the reference's annotations (top-level names) and
    reqtrace's own view of the final workspace."""
    expected = {(r, _top(i.qualname))
                for i in scan_text(t.reference, t.src_rel, is_test=False) for r in i.implements
                if r not in t.drop_reqs}
    ref_names = {_top(i.qualname) for i in scan_text(t.reference, t.src_rel, is_test=False)}
    out: dict[str, Any] = {}
    agent_src = ws / t.src_rel
    try:
        items = scan_text(agent_src.read_text(), t.src_rel, is_test=False)
        actual = {(r, _top(i.qualname)) for i in items for r in i.implements
                  if _top(i.qualname) in ref_names and r not in t.drop_reqs}
        out["impl_precision"] = len(actual & expected) / len(actual) if actual else 0.0
        out["impl_recall"] = len(actual & expected) / len(expected) if expected else None
    except (OSError, SyntaxError):
        out["impl_precision"] = out["impl_recall"] = 0.0
    d = tmp / "reqtrace"
    _copy_ws(ws, d)
    cfg = Config(root=d, source_dirs=["src"], test_dirs=["tests"])
    try:
        run_tests(cfg)
        m = build_matrix(load_context(cfg))
        scoped = [r for r in m.requirements if r.requirement.id not in t.drop_reqs]
        verified = [r for r in scoped if r.status.value in ("VERIFIED", "REVIEWED")]
        out.update({
            "req_coverage": len(verified) / len(scoped) if scoped else 0.0,
            "status": {r.requirement.id: r.status.value for r in m.requirements},
            "weakly_verified": sum(r.status.value == "WEAKLY_VERIFIED" for r in scoped),
            "unrequired_code": len(m.unrequired_code),
            "unrequired_items": m.unrequired_code,
        })
    except Exception as exc:  # noqa: BLE001 - a broken workspace scores zero, with reason
        out.update({"req_coverage": 0.0, "reqtrace_error": str(exc)[:300]})
    return out


def read_findings(ws: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    f = ws / "FINDINGS.json"
    if f.exists():
        try:
            data = json.loads(f.read_text())
            if isinstance(data, dict):
                data = data.get("findings", [])
            found += [x for x in data if isinstance(x, dict)]
        except (json.JSONDecodeError, ValueError):
            found.append({"kind": "_unparseable", "description": "FINDINGS.json not valid JSON"})
    issues = ws / ".reqtrace" / "issues.jsonl"
    if issues.exists():
        for line in issues.read_text().splitlines():
            if line.strip():
                i = json.loads(line)
                found.append({"req_id": i.get("req_id"), "kind": "requirement_issue",
                              "description": i.get("description", ""),
                              "related": i.get("related", []), "source": "reqtrace"})
    return found


def _changed_files(ws: Path, base_commit: str) -> list[str]:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=ws, capture_output=True, text=True).stdout
    changed = set(git("diff", "--name-only", base_commit).split())
    changed |= set(git("ls-files", "--others", "--exclude-standard").split())
    return sorted(c for c in changed if not c.startswith(".reqtrace/"))


def grade_review(ws: Path, t: Task, base_commit: str) -> dict[str, Any]:
    findings = read_findings(ws)
    truth = (t.spec.get("truth") or {}).get("defects", [])
    lines = defect_lines(t)
    matched: dict[str, bool] = {}
    used: set[int] = set()
    for d in truth:
        lo, hi = lines[d["id"]]
        hit = False
        for idx, f in enumerate(findings):
            kind_ok = f.get("kind") in d["kinds"]
            req_ok = d["req_ids"] is None or f.get("req_id") in d["req_ids"]
            try:
                line = int(f.get("line") or 0)
            except (TypeError, ValueError):
                line = 0
            loc_ok = lo - 3 <= line <= hi + 3
            kw_ok = any(k.lower() in str(f.get("description", "")).lower() for k in d["keywords"])
            if kind_ok and req_ok and (loc_ok or kw_ok):
                hit = True
                used.add(idx)
        matched[d["id"]] = hit
    false_pos = [f for i, f in enumerate(findings)
                 if i not in used and f.get("kind") in DEFECT_KINDS]
    other = [f for i, f in enumerate(findings)
             if i not in used and f.get("kind") not in DEFECT_KINDS]
    changed = [c for c in _changed_files(ws, base_commit) if c != "FINDINGS.json"]
    return {
        "defects_total": len(truth), "defects_found": sum(matched.values()),
        "detection_rate": sum(matched.values()) / len(truth) if truth else None,
        "defects_matched": matched,
        "false_positives": len(false_pos), "other_findings": len(other),
        "findings_total": len(findings),
        "edited_files": changed, "edited_source": bool(changed),
        "task_success": all(matched.values()) and not false_pos and not changed,
        "findings": findings[:50],
    }


def grade_ambiguity_flag(ws: Path, t: Task) -> dict[str, Any]:
    target = set((t.spec.get("truth") or {}).get("ambiguous", []))
    findings = read_findings(ws)
    flagged = [f for f in findings
               if f.get("req_id") in target or set(f.get("related") or []) & target
               or any(r in str(f.get("description", "")) for r in target)]
    return {"ambiguity_flagged": bool(flagged), "requirement_findings": len(findings),
            "flags": flagged[:10]}


def grade_run(ws: Path, t: Task, base_commit: str) -> dict[str, Any]:
    out: dict[str, Any] = {"task": t.id, "type": t.type}
    with tempfile.TemporaryDirectory(prefix="grade_") as tmpd:
        tmp = Path(tmpd)
        if t.type == "review":
            out.update(grade_review(ws, t, base_commit))
            out["requirement_lint"] = len(reqmod.lint(reqmod.parse_requirements_text(
                t.requirements, "r.yaml")))
            return out
        out.update(grade_hidden(ws, t, tmp))
        out.update(grade_strength(ws, t, tmp))
        out.update(grade_trace(ws, t, tmp))
        if t.type == "ambiguity":
            amb = grade_ambiguity_flag(ws, t)
            out.update(amb)
            out["task_success"] = out["task_success"] and amb["ambiguity_flagged"]
        else:
            out["requirement_findings"] = len(read_findings(ws))
    return out


def self_check(t: Task) -> list[str]:
    """Validate a task: reference passes hidden tests, every mutant fails a hidden test for its
    requirement, and the starting workspace does not already pass."""
    from .tasks import materialize

    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="check_") as tmpd:
        tmp = Path(tmpd)
        ws = tmp / "ws"
        base = materialize(t, ws)
        if t.type == "review":
            defect_lines(t)
            g = grade_review(ws, t, base)
            if g["edited_source"]:
                problems.append("fresh workspace counted as edited")
            return problems
        h = tmp / "h"
        _copy_ws(ws, h)
        (h / t.src_rel).write_text(t.reference)
        (h / "hidden_tests").mkdir()
        (h / "hidden_tests" / "test_hidden.py").write_text(t.hidden_test)
        ref = run_pytest(h, "hidden_tests")
        if not ref or any(v["outcome"] != "passed" for v in ref.values()):
            bad = [n for n, v in ref.items() if v["outcome"] != "passed"] or "none ran"
            problems.append(f"reference fails hidden tests: {bad}")
        for rid, src in t.mutant_sources.items():
            (h / t.src_rel).write_text(src)
            res = run_pytest(h, "hidden_tests")
            killers = [n for n, v in res.items() if v["outcome"] != "passed"
                       and rid in v["verifies"]]
            if not killers:
                problems.append(f"mutant {rid} not detected by its hidden tests")
            collateral = sorted({r for n, v in res.items() if v["outcome"] != "passed"
                                 for r in v["verifies"]} - {rid})
            if collateral:  # requirements that share a boundary; informational only
                print(f"  note: {t.id} mutant {rid} also fails hidden tests of {collateral}")
        start = run_pytest(_overlay(ws, t, None, tmp, "start"), ".")
        if t.type in ("implement", "ambiguity"):
            (h / t.src_rel).write_text((ws / t.src_rel).read_text())
            res = run_pytest(h, "hidden_tests")
            if res and all(v["outcome"] == "passed" for v in res.values()):
                problems.append("stub already passes hidden tests")
        if t.type == "change":
            (h / t.src_rel).write_text((ws / t.src_rel).read_text())
            res = run_pytest(h, "hidden_tests")
            if res and all(v["outcome"] == "passed" for v in res.values()):
                problems.append("pre-change code already passes post-change hidden tests")
            if start and any(v["outcome"] != "passed" for v in start.values()):
                problems.append("pre-change visible tests fail on pre-change code")
    return problems
