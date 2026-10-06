"""Project configuration (`.reqtrace.yaml`) and repository-root safety."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILE = ".reqtrace.yaml"
STATE_DIR = ".reqtrace"


class ReqtraceError(Exception):
    """An expected, user-actionable error. The MCP layer turns these into ToolErrors."""


@dataclass
class GateThresholds:
    max_unimplemented: int = 0
    max_untested: int = 0
    max_failing: int = 0
    max_weakly_verified: int = 0
    max_unrequired: int = 0


CPP_TEST_PATTERNS = ["*_test.*", "*_tests.*", "*_unittest.*", "*_unittests.*", "test_*.*"]


@dataclass
class TestBinary:
    """A C/C++ test executable. `gtest` binaries are run one test at a time; `exe` binaries
    are one test each (exit 0 passes, 77 skips, anything else fails)."""

    __test__ = False

    binary: str
    kind: str = "gtest"
    source: str | None = None  # exe: the file whose `main` carries `// verifies:`
    args: list[str] = field(default_factory=list)


@dataclass
class Config:
    root: Path
    source_dirs: list[str] = field(default_factory=lambda: ["src"])
    test_dirs: list[str] = field(default_factory=lambda: ["tests"])
    requirements: str = "requirements"
    python: str | None = None
    pytest_args: list[str] = field(default_factory=list)
    timeout_s: int = 300
    ignore_private: bool = True
    ignore: list[str] = field(default_factory=lambda: ["**/__init__.py"])
    gate: GateThresholds = field(default_factory=GateThresholds)
    # C and C++ (language: cpp)
    language: str = "python"
    test_file_patterns: list[str] = field(default_factory=list)
    build_commands: list[list[str]] = field(default_factory=list)
    build_dir: str = ".reqtrace/build"
    tests: list[TestBinary] = field(default_factory=list)
    mcdc: bool = True
    cc: str | None = None
    cxx: str | None = None

    @property
    def is_cpp(self) -> bool:
        return self.language == "cpp"

    def expand(self, arg: str) -> str:
        """Substitute {build_dir} and {root} in build commands and binary paths. Build
        commands also get {cc}, {cxx} and {coverage_flags} (see cpp_runner.build)."""
        return arg.replace("{build_dir}", str(self.root / self.build_dir)).replace(
            "{root}", str(self.root)
        )

    @property
    def state_dir(self) -> Path:
        return self.root / STATE_DIR

    def resolve_python(self) -> str:
        """The interpreter for the *target* repo's tests, not the server's own.

        Order: config `python`, a `.venv` in the repo, then `python3` on PATH while skipping
        the server's own environment (under uvx, PATH starts with reqtrace's private venv,
        which has no access to the repo's dependencies).
        """
        if self.python:
            return self.python
        for cand in (".venv/bin/python", ".venv/Scripts/python.exe"):
            p = self.root / cand
            if p.exists():
                return str(p)
        found = shutil.which("python3", path=os.pathsep.join(clean_path()))
        return found or "python3"


def own_env_dirs() -> set[str]:
    """Bin directories belonging to the environment this process runs in."""
    dirs = {str(Path(sys.executable).parent), str(Path(sys.prefix) / "bin")}
    if sys.prefix != sys.base_prefix:  # inside a virtualenv
        dirs.add(str(Path(sys.prefix) / "Scripts"))
    if os.environ.get("VIRTUAL_ENV"):
        dirs.add(str(Path(os.environ["VIRTUAL_ENV"]) / "bin"))
    return dirs if sys.prefix != sys.base_prefix or os.environ.get("VIRTUAL_ENV") else set()


def clean_path() -> list[str]:
    """PATH without the server's own virtualenv."""
    own = own_env_dirs()
    return [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and d not in own]


def find_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Repository root: explicit arg, then CLAUDE_PROJECT_DIR, then the working directory."""
    raw = explicit or os.environ.get("REQTRACE_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
    root = Path(raw) if raw else Path.cwd()
    root = root.resolve()
    if not root.is_dir():
        raise ReqtraceError(f"Repository root {root} is not a directory")
    return root


def load_config(root: Path) -> Config:
    cfg = Config(root=root)
    path = root / CONFIG_FILE
    if not path.exists():
        return cfg
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ReqtraceError(f"{CONFIG_FILE} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ReqtraceError(f"{CONFIG_FILE} must be a mapping")
    known = {
        "source_dirs",
        "test_dirs",
        "requirements",
        "python",
        "pytest_args",
        "timeout_s",
        "unrequired_code",
        "gate",
        "language",
        "test_file_patterns",
        "build",
        "tests",
        "coverage",
        "toolchain",
    }
    unknown = set(data) - known
    if unknown:
        raise ReqtraceError(f"{CONFIG_FILE}: unknown keys {sorted(unknown)}")
    for key in ("source_dirs", "test_dirs", "pytest_args"):
        if key in data:
            val = data[key]
            if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
                raise ReqtraceError(f"{CONFIG_FILE}: {key} must be a list of strings")
            setattr(cfg, key, val)
    if "requirements" in data:
        cfg.requirements = str(data["requirements"])
    if "python" in data:
        cfg.python = str(data["python"])
    if "timeout_s" in data:
        cfg.timeout_s = int(data["timeout_s"])
    unreq = data.get("unrequired_code") or {}
    if "ignore_private" in unreq:
        cfg.ignore_private = bool(unreq["ignore_private"])
    if "ignore" in unreq:
        cfg.ignore = [str(x) for x in unreq["ignore"]]
    gate = data.get("gate") or {}
    for key, val in gate.items():
        if not hasattr(cfg.gate, key):
            raise ReqtraceError(f"{CONFIG_FILE}: unknown gate threshold {key!r}")
        setattr(cfg.gate, key, int(val))
    _load_cpp(cfg, data)
    for d in [*cfg.source_dirs, *cfg.test_dirs, cfg.requirements, cfg.build_dir]:
        safe_path(root, d)
    return cfg


def _str_list(val: Any, what: str) -> list[str]:
    if not isinstance(val, list) or not all(isinstance(v, (str, int, float)) for v in val):
        raise ReqtraceError(f"{CONFIG_FILE}: {what} must be a list of strings")
    return [str(v) for v in val]


def _load_cpp(cfg: Config, data: dict[str, Any]) -> None:
    lang = str(data.get("language", "python")).lower()
    aliases = {"python": "python", "py": "python", "c": "cpp", "cpp": "cpp", "c++": "cpp"}
    if lang not in aliases:
        raise ReqtraceError(f"{CONFIG_FILE}: language must be python, c or cpp, not {lang!r}")
    cfg.language = aliases[lang]
    if cfg.is_cpp:
        cfg.test_file_patterns = list(CPP_TEST_PATTERNS)
        if "ignore" not in (data.get("unrequired_code") or {}):
            cfg.ignore = []  # the Python default (**/__init__.py) means nothing here
    if "test_file_patterns" in data:
        cfg.test_file_patterns = _str_list(data["test_file_patterns"], "test_file_patterns")
    build = data.get("build") or {}
    if not isinstance(build, dict):
        raise ReqtraceError(f"{CONFIG_FILE}: build must be a mapping")
    if "dir" in build:
        cfg.build_dir = str(build["dir"])
    cfg.build_commands = [
        _str_list(c, "each build command (an argv list, not a shell string)")
        for c in build.get("commands") or []
    ]
    for t in data.get("tests") or []:
        if not isinstance(t, dict) or "binary" not in t:
            raise ReqtraceError(f"{CONFIG_FILE}: each tests entry needs a `binary`")
        kind = str(t.get("kind", "gtest"))
        if kind not in ("gtest", "exe"):
            raise ReqtraceError(f"{CONFIG_FILE}: test kind must be gtest or exe, not {kind!r}")
        cfg.tests.append(
            TestBinary(
                binary=str(t["binary"]),
                kind=kind,
                source=str(t["source"]) if t.get("source") else None,
                args=_str_list(t.get("args", []), "tests[].args"),
            )
        )
    cov = data.get("coverage") or {}
    if "mcdc" in cov:
        cfg.mcdc = bool(cov["mcdc"])
    tc = data.get("toolchain") or {}
    cfg.cc = str(tc["cc"]) if tc.get("cc") else None
    cfg.cxx = str(tc["cxx"]) if tc.get("cxx") else None
    if cfg.is_cpp and not cfg.tests:
        raise ReqtraceError(f"{CONFIG_FILE}: language cpp needs a `tests:` list of test binaries")


def safe_path(root: Path, rel: str | os.PathLike[str]) -> Path:
    """Resolve `rel` inside `root`, rejecting anything that escapes it (symlinks included)."""
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ReqtraceError(f"Path {str(rel)!r} is outside the repository root") from exc
    return candidate


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()
