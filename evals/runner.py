"""Run Claude Code headless on a task, in an isolated workspace and HOME, then grade it.

Conditions differ by exactly one thing: `reqtrace` adds `--plugin-dir <this repo>` (MCP server,
skill, sub-agents, hook). Both get the same prompt, workspace, model, tools and limits.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .grade import grade_run
from .tasks import Task, materialize

REPO_ROOT = Path(__file__).resolve().parent.parent
RT_PREFIX = "mcp__plugin_reqtrace_reqtrace__"

BASE_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep", "TodoWrite", "Agent", "Skill",
    "Bash(python3 -m pytest)", "Bash(python3 -m pytest *)", "Bash(pytest)", "Bash(pytest *)",
    "Bash(git diff *)", "Bash(git log *)", "Bash(git show *)", "Bash(git status *)",
]
CONDITIONS = {"baseline": BASE_TOOLS, "reqtrace": [*BASE_TOOLS, f"{RT_PREFIX}*"]}

# The hosted workspace this was built in injects settings into child Claude sessions (skip
# plugin MCP servers, sync this session's skills, reuse its session id). Remove them so each
# run is a clean, independent session. Harmless where they are not set.
STRIP_ENV = [
    "CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS", "CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS_EXCEPT",
    "CLAUDE_CODE_SYNC_PLUGINS", "CLAUDE_CODE_SYNC_SKILLS", "CLAUDE_CODE_CCR_EARLY_PLUGINS_SYNC",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID",
    "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD", "CLAUDE_ADDITIONAL_DIRECTORIES",
    "CLAUDE_PROJECT_DIR", "REQTRACE_ROOT", "VIRTUAL_ENV",
]
INFRA_MARKERS = ("rate limit", "usage limit", "overloaded", "429", "529", "api error",
                 "authentication", "timed out")


def agent_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    env["HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def versions() -> dict[str, str]:
    def out(cmd: list[str]) -> str:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "unavailable"
    from importlib.metadata import version

    return {
        "claude_code": out(["claude", "--version"]),
        "mcp_sdk": version("mcp"),
        "reqtrace": out(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"])
        + (" (dirty)" if out(["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--",
                                "src", "skills", "agents", "hooks", ".claude-plugin"]) else ""),
        "python": out(["python3", "--version"]),
    }


def prewarm() -> None:
    """Build the plugin's server once so the first treatment run doesn't pay for it."""
    subprocess.run(["uvx", "--quiet", "--from", str(REPO_ROOT), "reqtrace-mcp", "--version"],
                   capture_output=True, timeout=600, check=True)


def parse_stream(path: Path) -> dict[str, Any]:
    main: Counter[str] = Counter()
    sub: Counter[str] = Counter()
    skills: list[str] = []
    agents: list[str] = []
    result: dict[str, Any] = {}
    init: dict[str, Any] = {}
    if not path.exists():
        return {"parse_error": "no stream"}
    for line in path.read_text(errors="replace").splitlines():
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        if m.get("type") == "system" and m.get("subtype") == "init":
            init = m
        elif m.get("type") == "assistant":
            for b in m.get("message", {}).get("content", []):
                if b.get("type") != "tool_use":
                    continue
                (sub if m.get("parent_tool_use_id") else main)[b["name"]] += 1
                if b["name"] == "Skill":
                    skills.append(str(b.get("input", {}).get("skill")))
                if b["name"] == "Agent":
                    agents.append(str(b.get("input", {}).get("subagent_type")))
        elif m.get("type") == "result":
            result = m
    usage = result.get("usage") or {}
    all_tools = main + sub
    return {
        "subtype": result.get("subtype"), "is_error": result.get("is_error"),
        "num_turns": result.get("num_turns"), "duration_s": (result.get("duration_ms") or 0) / 1000,
        "cost_usd_list": result.get("total_cost_usd"),
        "input_tokens": usage.get("input_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "tool_calls": sum(all_tools.values()),
        "reqtrace_calls": sum(v for k, v in all_tools.items() if k.startswith(RT_PREFIX)),
        "tools_main": dict(main), "tools_subagents": dict(sub),
        "skills_invoked": skills, "agents_invoked": agents,
        "permission_denials": [d.get("tool_name") for d in result.get("permission_denials", [])],
        "result_text": (result.get("result") or "")[-3000:],
        "model": init.get("model"),
        "plugins_loaded": [p.get("name") for p in init.get("plugins", [])],
        "mcp_servers": [s.get("name") for s in init.get("mcp_servers", [])],
    }


def check_workdir(work_root: Path) -> Path:
    """Workspaces must be outside this repo: Claude Code protects a loaded plugin's directory
    from edits, so a workspace inside it would deny the reqtrace arm every write."""
    work_root = work_root.resolve()
    if work_root == REPO_ROOT or REPO_ROOT in work_root.parents:
        raise SystemExit(f"--workdir {work_root} must be outside {REPO_ROOT}")
    return work_root


def run_one(t: Task, condition: str, run_idx: int, out_root: Path, work_root: Path, model: str,
            timeout_s: int = 1500, force: bool = False) -> dict[str, Any]:
    """Results (run.json, stream.jsonl) go under out_root; the workspace and HOME go under
    work_root, which must be outside the repo. All paths absolute: HOME is resolved relative
    to the agent's cwd otherwise."""
    out_root, work_root = out_root.resolve(), check_workdir(work_root)
    rdir = out_root / "runs" / t.id / condition / f"r{run_idx}"
    wdir = work_root / t.id / condition / f"r{run_idx}"
    done = rdir / "run.json"
    if done.exists() and not force:
        prev = json.loads(done.read_text())
        if prev.get("status") == "ok":
            return prev
    for d in (rdir, wdir):
        if d.exists():
            shutil.rmtree(d)
    rdir.mkdir(parents=True)
    ws, home = wdir / "ws", wdir / "home"
    home.mkdir(parents=True)
    base = materialize(t, ws)
    cmd = ["claude", "-p", t.prompt, "--model", model, "--output-format", "stream-json",
           "--verbose", "--max-turns", str(t.max_turns), "--permission-mode", "dontAsk",
           "--allowedTools", ",".join(CONDITIONS[condition])]
    if condition == "reqtrace":
        cmd += ["--plugin-dir", str(REPO_ROOT)]
    t0 = time.monotonic()
    timed_out = False
    with (rdir / "stream.jsonl").open("w") as so, (rdir / "stderr.txt").open("w") as se:
        try:
            proc = subprocess.run(cmd, cwd=ws, env=agent_env(home), stdin=subprocess.DEVNULL,
                                  stdout=so, stderr=se, timeout=timeout_s)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out, exit_code = True, -1
    wall = time.monotonic() - t0
    meta = parse_stream(rdir / "stream.jsonl")
    text = (meta.get("result_text", "") + (rdir / "stderr.txt").read_text()[-2000:]).lower()
    infra = (exit_code != 0 or meta.get("is_error")) and any(k in text for k in INFRA_MARKERS)
    record: dict[str, Any] = {
        "task": t.id, "type": t.type, "condition": condition, "run": run_idx, "model": model,
        "exit_code": exit_code, "timed_out": timed_out, "wall_s": round(wall, 1),
        "base_commit": base, "workspace": str(ws), **meta,
    }
    if infra and not timed_out:
        record["status"] = "infra_error"
    else:
        try:
            record["grade"] = grade_run(ws, t, base)
            record["status"] = "ok"
        except Exception as exc:  # noqa: BLE001 - keep the run, flag the grader failure
            record["status"] = "grader_error"
            record["grader_error"] = repr(exc)[:500]
    done.write_text(json.dumps(record, indent=1, default=str))
    shutil.rmtree(home, ignore_errors=True)  # holds a copy of auth/config; don't keep it
    return record
