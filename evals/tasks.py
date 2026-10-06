"""Benchmark tasks: load task specs and build the workspace the agent sees.

A task = a domain (requirements, stub, reference, hidden tests, mutants) + a task type +
optional patches. Everything hidden (reference, mutants, hidden tests, ground truth) stays
outside the agent's workspace and is only used by the grader.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EVALS = Path(__file__).resolve().parent
DOMAINS = EVALS / "domains"
TASKS = EVALS / "tasks"
CONTRIBUTING = EVALS / "workspace_CONTRIBUTING.md"

PYTEST_INI = """[pytest]
pythonpath = src
markers =
    verifies(*req_ids): requirements this test verifies
"""
RECTRACE_YAML = "source_dirs: [src]\ntest_dirs: [tests]\n"
GITIGNORE = "__pycache__/\n.pytest_cache/\n.reqtrace/runs/\n.coverage\n"


def patch(text: str, pairs: list[list[str]], what: str) -> str:
    for old, new in pairs:
        n = text.count(old)
        if n != 1:
            raise ValueError(f"{what}: patch target found {n} times: {old[:60]!r}")
        text = text.replace(old, new)
    return text


@dataclass
class Domain:
    name: str
    package: str
    module: str
    requirements: str
    stub: str
    reference: str
    hidden_test: str
    visible_test: str
    mutants: dict[str, list[list[str]]]

    @classmethod
    def load(cls, name: str) -> Domain:
        d = DOMAINS / name
        meta = yaml.safe_load((d / "domain.yaml").read_text())
        return cls(name=name, package=meta["package"], module=meta["module"],
                   requirements=(d / "requirements.yaml").read_text(),
                   stub=(d / "stub.py").read_text(), reference=(d / "reference.py").read_text(),
                   hidden_test=(d / "hidden_test.py").read_text(),
                   visible_test=(d / "visible_test.py").read_text(),
                   mutants=yaml.safe_load((d / "mutants.yaml").read_text()))


@dataclass
class Task:
    id: str
    type: str
    prompt: str
    max_turns: int
    domain: Domain
    spec: dict[str, Any]
    # Final truth after any change/variant patches:
    requirements: str = ""
    reference: str = ""
    stub: str = ""
    hidden_test: str = ""
    mutant_sources: dict[str, str] = field(default_factory=dict)
    drop_reqs: list[str] = field(default_factory=list)

    @property
    def src_rel(self) -> str:
        return f"src/{self.domain.package}/{self.domain.module}.py"

    @property
    def import_path(self) -> str:
        return f"{self.domain.package}.{self.domain.module}"


def load_task(task_id: str) -> Task:
    d = TASKS / task_id
    spec = yaml.safe_load((d / "task.yaml").read_text())
    dom = Domain.load(spec["domain"])
    t = Task(id=task_id, type=spec["type"], prompt=spec["prompt"].strip(),
             max_turns=int(spec.get("max_turns", 40)), domain=dom, spec=spec)
    mods = spec.get("change") or spec.get("variant") or {}
    t.requirements = patch(dom.requirements, mods.get("requirements", []), f"{task_id} reqs")
    t.reference = patch(dom.reference, mods.get("reference", []), f"{task_id} reference")
    t.stub = patch(dom.stub, mods.get("stub", []), f"{task_id} stub")
    t.hidden_test = patch(dom.hidden_test, mods.get("hidden_test", []), f"{task_id} hidden")
    t.hidden_test += mods.get("hidden_test_append", "")
    t.drop_reqs = list(mods.get("drop_requirements_from_grading", []))
    mutants = {**dom.mutants, **mods.get("mutants", {})}
    t.mutant_sources = {
        rid: patch(t.reference, pairs, f"{task_id} mutant {rid}")
        for rid, pairs in mutants.items() if rid not in t.drop_reqs
    }
    return t


def all_task_ids() -> list[str]:
    return sorted(p.name for p in TASKS.iterdir() if (p / "task.yaml").exists())


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _write_workspace(root: Path, t: Task, requirements: str, source: str,
                     visible_test: str | None) -> None:
    pkg = root / "src" / t.domain.package
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (root / t.src_rel).write_text(source)
    tests = root / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "conftest.py").write_text("")
    if visible_test is not None:
        (tests / f"test_{t.domain.module}.py").write_text(visible_test)
    (root / "requirements").mkdir(exist_ok=True)
    (root / "requirements" / f"{t.domain.package}.yaml").write_text(requirements)
    shutil.copy(CONTRIBUTING, root / "CONTRIBUTING.md")
    (root / "pytest.ini").write_text(PYTEST_INI)
    (root / ".reqtrace.yaml").write_text(RECTRACE_YAML)
    (root / ".gitignore").write_text(GITIGNORE)


def materialize(t: Task, root: Path) -> str:
    """Create the agent's workspace. Returns the git commit the grader diffs against."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    dom = t.domain
    if t.type in ("implement", "ambiguity"):
        _write_workspace(root, t, t.requirements, t.stub, None)
    elif t.type == "review":
        defective = patch(t.reference, t.spec.get("defects_applied", []), f"{t.id} defects")
        # Remove trace comments that would give the defect away? No: reviewers see annotated
        # code in real life. Keep them.
        _write_workspace(root, t, t.requirements, defective, dom.visible_test)
    elif t.type == "change":
        _write_workspace(root, t, dom.requirements, dom.reference, dom.visible_test)
    else:
        raise ValueError(f"unknown task type {t.type}")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "Initial version")
    if t.type == "change":
        (root / "requirements" / f"{dom.package}.yaml").write_text(t.requirements)
        _git(root, "commit", "-qam", f"Change requirements for {dom.package}")
    return _git(root, "rev-parse", "HEAD")


def defect_lines(t: Task) -> dict[str, tuple[int, int]]:
    """For review tasks: defect id -> (line, line) where it sits in the workspace source."""
    defective = patch(t.reference, t.spec.get("defects_applied", []), f"{t.id} defects")
    lines = defective.splitlines()
    out: dict[str, tuple[int, int]] = {}
    for d in (t.spec.get("truth") or {}).get("defects", []):
        idx = [i + 1 for i, ln in enumerate(lines) if d["line_match"] in ln]
        if len(idx) != 1:
            raise ValueError(f"{t.id}: line_match {d['line_match']!r} found {len(idx)} times")
        out[d["id"]] = (idx[0], idx[0])
    return out
