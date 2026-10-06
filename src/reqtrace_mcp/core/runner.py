"""Run the target repo's tests under coverage, with per-test contexts.

Security: the only process started is the repo's own Python running `coverage run -m pytest`.
The argv is built here from config; no caller ever supplies a command. No shell is used.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config, ReqtraceError
from .model import CoverageFigures, RunSummary, TestOutcome

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "_plugin"
PARAM_RE = re.compile(r"\[.*\]$")


def runs_dir(cfg: Config) -> Path:
    return cfg.state_dir / "runs"


def latest_run_id(cfg: Config) -> str | None:
    p = runs_dir(cfg) / "LATEST"
    return p.read_text().strip() if p.exists() else None


def run_fingerprint(cfg: Config, run_id: str) -> str | None:
    p = runs_dir(cfg) / run_id / "fingerprint.txt"
    return p.read_text().strip() if p.exists() else None


def load_run(cfg: Config, run_id: str | None = None) -> RunSummary | None:
    run_id = run_id or latest_run_id(cfg)
    if not run_id or not re.fullmatch(r"[0-9TZ]+-[0-9a-f]{6}", run_id):
        return None
    p = runs_dir(cfg) / run_id / "run.json"
    return RunSummary.model_validate_json(p.read_text()) if p.exists() else None


def fingerprint(cfg: Config) -> str:
    """Hash of every Python file under source and test dirs: tells us if results are stale."""
    import hashlib

    h = hashlib.sha256()
    for d in [*cfg.source_dirs, *cfg.test_dirs]:
        base = cfg.root / d
        files = [base] if base.is_file() else sorted(base.rglob("*.py")) if base.is_dir() else []
        for f in files:
            h.update(f.relative_to(cfg.root).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def _check_env(python: str, cfg: Config) -> None:
    try:
        proc = subprocess.run(
            [python, "-c", "import pytest, coverage"],
            cwd=cfg.root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise ReqtraceError(
            f"Python interpreter {python!r} not found. Set `python:` in "
            ".reqtrace.yaml to the repo's interpreter."
        ) from exc
    if proc.returncode != 0:
        raise ReqtraceError(
            f"{python} cannot import pytest and coverage. Install them in the repo's "
            f"environment (pip install pytest coverage). Detail: {proc.stderr.strip()[-300:]}"
        )


def run_tests(cfg: Config, node_ids: list[str] | None = None) -> RunSummary:
    python = cfg.resolve_python()
    _check_env(python, cfg)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    rdir = runs_dir(cfg) / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    results_file = rdir / "results.json"
    (rdir / "fingerprint.txt").write_text(fingerprint(cfg))
    cmd = [
        python,
        "-m",
        "coverage",
        "run",
        "--branch",
        f"--data-file={rdir / '.coverage'}",
        f"--source={','.join(cfg.source_dirs)}",
        "-m",
        "pytest",
        "-p",
        "reqtrace_pytest_plugin",
        "-p",
        "no:cacheprovider",
        f"--rootdir={cfg.root}",
        "-q",
        *cfg.pytest_args,
        *(node_ids or []),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(PLUGIN_DIR), env.get("PYTHONPATH")]))
    env["REQTRACE_RESULTS"] = str(results_file)
    env.pop("COVERAGE_PROCESS_START", None)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.monotonic()
    timed_out = False
    proc = subprocess.Popen(
        cmd,
        cwd=cfg.root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=cfg.timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
    duration = time.monotonic() - t0
    tests: list[TestOutcome] = []
    if results_file.exists():
        data: dict[str, Any] = json.loads(results_file.read_text())
        tests = [TestOutcome.model_validate(t) for t in data.get("tests", [])]
    elif not timed_out and proc.returncode not in (0, 5):
        raise ReqtraceError(
            "Test run produced no results (collection or import error?). Output tail:\n"
            + (out + err).strip()[-1500:]
        )
    (rdir / "output.txt").write_text(out + "\n--- stderr ---\n" + err, encoding="utf-8")
    summary = RunSummary(
        run_id=run_id,
        started_at=started,
        duration_s=round(duration, 2),
        exit_code=proc.returncode if proc.returncode is not None else -1,
        command=[os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)],
        tests=tests,
        timed_out=timed_out,
        stderr_tail=(out + err).strip()[-800:],
    )
    (rdir / "run.json").write_text(summary.model_dump_json(indent=1), encoding="utf-8")
    (runs_dir(cfg) / "LATEST").write_text(run_id)
    return summary


# ---------------------------------------------------------------- coverage ---


class CoverageIndex:
    """Per-test executed lines and per-file statement/branch data for one run."""

    def __init__(self, cfg: Config, run_id: str) -> None:
        import coverage

        self.cfg = cfg
        self.data_file = runs_dir(cfg) / run_id / ".coverage"
        self.available = self.data_file.exists()
        self.lines_by_test: dict[str, dict[str, set[int]]] = {}
        self.files: dict[str, dict[str, Any]] = {}
        if not self.available:
            return
        data = coverage.CoverageData(basename=str(self.data_file))
        data.read()
        for abs_file in data.measured_files():
            relp = self._rel(abs_file)
            if relp is None:
                continue
            for line, ctxs in data.contexts_by_lineno(abs_file).items():
                for ctx in ctxs:
                    if not ctx:
                        continue
                    base = PARAM_RE.sub("", ctx)
                    self.lines_by_test.setdefault(base, {}).setdefault(relp, set()).add(line)
        cov = coverage.Coverage(data_file=str(self.data_file))
        cov.load()
        report_path = runs_dir(cfg) / run_id / "coverage.json"
        try:
            cov.json_report(outfile=str(report_path), show_contexts=False)
        except coverage.exceptions.NoDataError:
            return
        report = json.loads(report_path.read_text())
        for name, info in report.get("files", {}).items():
            relp = self._rel(name)
            if relp is not None:
                self.files[relp] = info

    def _rel(self, name: str) -> str | None:
        p = Path(name)
        cands = [p] if p.is_absolute() else [self.cfg.root / p, Path.cwd() / p]
        for c in cands:
            try:
                return c.resolve().relative_to(self.cfg.root).as_posix()
            except (ValueError, OSError):
                continue
        return None

    def test_hits(self, nodeid: str, path: str, first: int, last: int) -> bool:
        lines = self.lines_by_test.get(nodeid, {}).get(path, set())
        return any(first <= ln <= last for ln in lines)

    def figures(self, spans: list[tuple[str, int, int]]) -> CoverageFigures:
        fig = CoverageFigures()
        for path, first, last in spans:
            info = self.files.get(path)
            if not info:
                continue
            executed = {ln for ln in info.get("executed_lines", []) if first <= ln <= last}
            missing = {ln for ln in info.get("missing_lines", []) if first <= ln <= last}
            fig.statements += len(executed) + len(missing)
            fig.statements_covered += len(executed)
            fig.missing_lines += [f"{path}:{ln}" for ln in sorted(missing)]
            eb = [b for b in info.get("executed_branches", []) if first <= b[0] <= last]
            mb = [b for b in info.get("missing_branches", []) if first <= b[0] <= last]
            fig.branches += len(eb) + len(mb)
            fig.branches_covered += len(eb)
            fig.missing_branches += [f"{path}:{a}->{b if b > 0 else 'exit'}" for a, b in mb]
        return fig
