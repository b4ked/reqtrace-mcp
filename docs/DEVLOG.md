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
