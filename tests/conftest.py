from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from reqtrace_mcp.core.analysis import Context, load_context
from reqtrace_mcp.core.config import Config, load_config

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "altitude-alerter"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fresh copy of the example repo, committed to its own git history."""
    dst = tmp_path / "alerter"
    shutil.copytree(EXAMPLE, dst, ignore=shutil.ignore_patterns(".reqtrace", "__pycache__"))
    git(dst, "init", "-q", "-b", "main")
    git(dst, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    git(dst, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return dst


@pytest.fixture
def cfg(repo: Path) -> Config:
    return load_config(repo)


def ctx_of(cfg: Config) -> Context:
    return load_context(cfg)
