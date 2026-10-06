# Dev log

## 2026-10-06 — M0 research and spike

**Checked current docs** (MCP 2026-07-28 spec, Python SDK 2.3.0, Claude Code 2.1.291 docs on MCP, skills, sub-agents, plugins, hooks, headless, plugin evals).

Things that would have gone wrong had I built from memory:
- `FastMCP` is gone in SDK v2: it is `MCPServer`, imported from `mcp.server`. Most tutorials online still show v1.
- The 2026-07-28 protocol is stateless: no `initialize` handshake, no sessions. Any cross-call state has to live somewhere explicit. Our state lives in `.reqtrace/` in the repo, which suits evidence anyway.
- Roots, sampling and protocol logging are deprecated. So the repo root comes from config/`CLAUDE_PROJECT_DIR`, and the server never calls an LLM.
- In v2, only a `ToolError`'s message reaches the model; other exceptions become a generic "Error executing tool". Useful: internal errors don't leak, but expected errors must be `ToolError`.
- Plugin MCP tools are named `mcp__plugin_<plugin>_<server>__<tool>`; hook matchers and agent `tools` lists must use that full form.
- Plugin sub-agents ignore `hooks`, `mcpServers`, `permissionMode`.
- `claude plugin eval` exists and does with/without baselines, but has no code graders.

**Spike results** (scratch code, not committed):
- `@mcp.tool(annotations=..., meta=...)` puts `readOnlyHint` and `anthropic/requiresUserInteraction` on the wire (verified via `list_tools`).
- `MCPServer` + in-memory `Client(server)`: negotiated `2026-07-28`; structured output and `outputSchema` generated from return types; `ToolError` returned `is_error=True` with my message; resource and prompt round-trip fine.
- `pytest --junitxml`: markers are **not** in the XML → need our own pytest plugin to record `verifies` links with outcomes.
- `coverage json` report: **no per-test contexts** even with `--cov-context=test` → read `.coverage` via `CoverageData.contexts_by_lineno()`, which worked and showed exactly which test hit which line.
- In the toy repo, the unannotated `extra_feature()` showed only import-time coverage: a clean example of "unrequired code" for the README.

**Open risk for M1:** coverage's `dynamic_context = test_function` names contexts differently from pytest node IDs (`pkg.test_mod.test_fn` vs `tests/test_mod.py::test_fn`). Need a mapping, including parametrised tests.

## 2026-10-06 — M1–M3 build and first live runs

- M1 worked on the example first time; the most useful early fix was making `failing` gaps name
  the exact parametrised case and its assertion, because that's what an agent needs to act.
- In-memory MCP client tests surfaced that a client without elicitation support gets a
  protocol error from `record_review` (-32021), before the tool body runs. That is the right
  outcome (nothing recorded) but it arrives as an exception group in-process.
- **First live Claude Code run found a real bug.** The plugin starts the server with
  `uvx --from <plugin dir>`. uvx puts its private venv first on PATH, so `python3` resolved to
  reqtrace's own interpreter, which has no access to the repo's pytest. Unit tests never saw
  this because they run in one environment. Fix: resolve the target interpreter with the
  server's venv removed from PATH, and run tests in that cleaned environment.
- uv caches `--from <dir>` builds keyed on `pyproject.toml` only, so source edits were not
  picked up. Added `[tool.uv] cache-keys` for `src/**/*.py`.
- The hosted workspace tells child Claude sessions to skip plugin MCP servers
  (`CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS=1`) and to sync this session's skills. For clean,
  comparable eval runs the harness removes those variables and gives each run a fresh `HOME`.
- Second live run (after the fix): skill auto-loaded, ALT-004 implemented, weak ALT-002 test
  replaced, a real ambiguity in ALT-004 flagged, independent verifier found a real defect
  (invalid altitude short-circuited floor validation), all four requirements VERIFIED.
  21 turns, ~$0.29 list price. Run-to-run variance already visible: run 1 marked
  `altitude_in_metres` as derived, run 2 left it for the human.

## 2026-10-06 — M4 benchmark and pilot

- Ten tasks over four invented domains (battery controller, joint limits, thruster limiter,
  depth alarm): 4 implement, 2 requirement-change, 3 review (one clean control), 1 conflict.
- `evals check` failed on the first try for two good reasons: Python reused a cached `.pyc`
  between two mutants of the same size written in the same second (fix:
  `PYTHONDONTWRITEBYTECODE=1` in graded runs), and one of my hidden test expectations was
  wrong (the reference was right).
- First pilot was invalid. Workspaces were inside the plugin directory, which Claude Code
  protects, so only the reqtrace arm was denied writes. Also `HOME` was a relative path, so
  each agent's home directory was created inside its own workspace. Both fixed (ADR-013).
- Valid pilot (2 tasks × 2 arms × 1 run, Sonnet 5.5): both arms solved both tasks. Differences
  were in test-to-requirement link precision (0.71 vs 0.37) and cost (11 vs 5.5 turns,
  $0.16 vs $0.12 list). In the review task the reqtrace arm did not load the skill or call
  any reqtrace tool. Ceiling risk: these tasks may be too easy for a strong model to show a
  difference in task success.
