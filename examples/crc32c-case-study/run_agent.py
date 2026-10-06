"""Ask Claude Code, with the reqtrace plugin, to close crc32c's verification gaps.

    python examples/crc32c-case-study/run_agent.py <workdir-outside-this-repo>

Clones a fresh annotated crc32c with setup.sh, then runs one headless Claude Code session with
the same locked-down settings as the benchmark (`dontAsk`, an allow-list without Bash). The
only way to build and run the C++ tests is reqtrace's `run_verification`. Prints a summary;
the raw stream stays in <workdir>/stream.jsonl (it contains account details, so don't publish
it).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from evals.runner import BASE_TOOLS, RT_PREFIX, agent_env, check_workdir, parse_stream  # noqa: E402

PROMPT = """This is google/crc32c. Its requirements are in requirements/crc32c.yaml and \
reqtrace is configured for this C++ repo.

Use reqtrace to find where the requirements are not fully verified, then close the gaps you \
can by adding or improving tests.

Rules:
- Change only test files (*_unittest.cc, *_unittests.h, *_unittest.c). Do not change library \
code, build files or the requirements.
- Link every test you add to the requirement it verifies.
- If a gap cannot be closed by a test on this machine, say why instead of hiding it.

Finish with a short summary: what you changed, and what is still open and why."""


def main() -> None:
    work = check_workdir(Path(sys.argv[1]))
    work.mkdir(parents=True, exist_ok=True)
    ws, home = work / "ws", work / "home"
    if ws.exists():
        raise SystemExit(f"{ws} exists; use a fresh workdir")
    home.mkdir(exist_ok=True)
    subprocess.run([str(HERE / "setup.sh"), str(ws)], check=True)
    tools = [t for t in BASE_TOOLS if "pytest" not in t] + [f"{RT_PREFIX}*"]
    model = sys.argv[2] if len(sys.argv) > 2 else "claude-sonnet-5-5"
    cmd = [
        "claude",
        "-p",
        PROMPT,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        "80",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        ",".join(tools),
        "--plugin-dir",
        str(REPO),
    ]
    with open(work / "stream.jsonl", "w") as out:
        subprocess.run(
            cmd,
            cwd=ws,
            env=agent_env(home),
            stdout=out,
            stdin=subprocess.DEVNULL,
            timeout=2400,
            check=False,
        )
    summary = parse_stream(work / "stream.jsonl")
    print(json.dumps({k: v for k, v in summary.items() if k != "result_text"}, indent=1))
    print(summary["result_text"])
    print(f"\nWorkspace: {ws}\nIndependent check: cd {ws} && reqtrace verify && reqtrace gaps")


if __name__ == "__main__":
    main()
