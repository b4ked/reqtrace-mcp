#!/usr/bin/env python3
"""PreToolUse hook: block `git commit` when traceability gaps exceed .reqtrace.yaml thresholds.

Reads the hook JSON on stdin. Does nothing unless the command is a git commit AND the project
uses reqtrace (has .reqtrace.yaml). Re-runs verification first so the gate never passes on
stale results. Exit 2 blocks the tool call and shows stderr to Claude.

Limitation: it only sees commits Claude makes through Bash. Humans can use the same check as
a git pre-commit hook: `reqtrace gate --verify`.
"""

import json
import os
import re
import subprocess
import sys

COMMIT_RE = re.compile(r"(^|[;&|]\s*|\s)git(\s+-[^\s]+(\s+[^\s-][^\s]*)?)*\s+commit\b")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    command = (payload.get("tool_input") or {}).get("command", "")
    if not COMMIT_RE.search(command):
        return 0
    root = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if not os.path.exists(os.path.join(root, ".reqtrace.yaml")):
        return 0
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    cmd = ["uvx", "--quiet", "--from", plugin_root, "reqtrace", "--root", root, "gate", "--verify"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=580)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"reqtrace commit gate could not run ({exc}); allowing commit.", file=sys.stderr)
        return 0
    if proc.returncode == 1:
        print(proc.stdout.strip() + "\nCommit blocked by reqtrace. Close the gaps above "
              "(see find_gaps), or ask a human to adjust thresholds in .reqtrace.yaml.",
              file=sys.stderr)
        return 2
    if proc.returncode != 0:
        print(f"reqtrace commit gate error, allowing commit: {proc.stderr.strip()[-400:]}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
