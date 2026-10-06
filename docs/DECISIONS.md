# Architecture decisions

Lightweight ADRs. Each: context, decision, trade-off, and the one-line interview answer.

---

## ADR-001 Python + official MCP SDK v2 (`MCPServer`)

**Context.** SDK 2.0 shipped on 2026-07-28 with the new protocol revision; 2.3.0 is current. v1 is in maintenance.
**Decision.** Build on `mcp>=2.3,<3` using the high-level `MCPServer`.
**Trade-off.** v2 is young (some ecosystem examples still show v1 `FastMCP`), but it serves both protocol eras from one server and gives an in-memory `Client(server)` for tests, which I verified in a spike.
**Interview line:** "I built on the current protocol, not the one in most tutorials, and checked it with a spike before committing."

## ADR-002 stdio first, Streamable HTTP later

**Context.** The user is a developer running Claude Code locally against a local repo; the server must read files and run tests there.
**Decision.** stdio in MVP. HTTP is cheap in the SDK but a remote server can't see a local repo, so it only makes sense for CI or a hosted service. Deferred to M6 if time allows.
**Trade-off.** Not usable from claude.ai web. Acceptable for a developer tool.

## ADR-003 YAML requirements with stable IDs

**Context.** Real programmes keep requirements in DOORS/Polarion and export them; reviewers need diffs.
**Decision.** One or more YAML files, a list of requirement objects (§3.1). YAML over Markdown because fields (acceptance, parent) need structure; over JSON because humans edit it.
**Trade-off.** No free-text ingestion in MVP. A `import_markdown` helper can come later; the eval doesn't need it.

## ADR-004 Comment annotations in code, pytest markers in tests

**Context.** Links must live next to the code so they survive refactors and show in diffs.
**Options.** (a) decorators in code: adds a runtime dependency to the product; (b) separate mapping file: drifts; (c) comments: zero dependency, visible in review.
**Decision.** `# implements: REQ-x` above a def/class; `@pytest.mark.verifies("REQ-x")` on tests (native pytest, no import needed).
**Trade-off.** Comments are just claims, so an agent could tag the wrong function. That's why status uses coverage (ADR-010) and the eval uses mutants: we never trust a link on its word.

## ADR-005 Ship as one Claude Code plugin, usable as a plain MCP server too

**Context.** The brief wants a server, a skill, two sub-agents and a hook. Claude Code plugins bundle all four, are installable from a GitHub repo acting as a marketplace, and are the unit `claude plugin eval` and `--plugin-dir` work with.
**Decision.** Repo = Python package + plugin. Server also installable alone (`claude mcp add … uvx`) for other MCP clients.
**Trade-off.** Plugin agents ignore `hooks`, `mcpServers` and `permissionMode` frontmatter, so the verifier's restrictions must come from its `tools` list. That is enough for "no edits".

## ADR-006 Server is deterministic; Claude does the reasoning

**Context.** "Where should reasoning happen?" was left open during scoping. MCP sampling (server asks the client's LLM) is deprecated in 2026-07-28 anyway.
**Decision.** The server never calls an LLM. It computes facts (links, coverage, results, diffs); the agent interprets them and proposes links/issues through tools that store them as unconfirmed.
**Trade-off.** Less "magic" in the server, but every server output is reproducible and auditable, which is the point of evidence. No API key needed to use it.

## ADR-007 Human sign-off enforced by protocol, not by prompt

**Context.** If an agent can call `record_review`, it can approve its own work. That defeats independence.
**Decision.** Mark the tool `anthropic/requiresUserInteraction` (Claude Code prompts every time, in every permission mode, and refuses it in `dontAsk`), and collect reviewer name + rationale by elicitation, not from tool arguments. CLI path for humans.
**Trade-off.** Other MCP clients may ignore the `_meta` hint; elicitation still keeps the identity out of the model's hands. Documented as a limitation.
**Interview line:** "Separation of duties has to be enforced by the system; a prompt saying 'don't approve your own work' is not a control."

## ADR-008 Custom eval harness on `claude -p --bare`, plus `claude plugin eval` later

**Context.** `claude plugin eval` gives with/without Δ for free but has no custom-code graders, so it can't run hidden tests or mutants.
**Decision.** Primary harness drives `claude -p --bare` (clean, reproducible baseline; treatment adds only `--plugin-dir`) and grades the final workspace in Python. Add a small `claude plugin eval` suite in M6 for skill triggering and tool order.
**Trade-off.** More code to own, but the metrics that matter (hidden tests, verification strength, defect detection) need it.

## ADR-009 Fair baseline: the convention is public to both arms

**Context.** If only the treatment knew the annotation format, trace metrics would be rigged.
**Decision.** Every task repo has a `CONTRIBUTING.md` describing the convention, seen by both arms. Graders re-derive everything from the final files. Skill-only ablation in M6 separates "instructions" from "tools".

## ADR-010 Per-test coverage to detect weak verification

**Context.** Traceability tools check that a test is *tagged* to a requirement, not that it *exercises* it.
**Decision.** Run tests under coverage with `dynamic_context = test_function`, read the `.coverage` DB directly (the JSON report omits contexts, found in the spike), and mark a requirement `WEAKLY_VERIFIED` when none of its linked tests executes its implementing code.
**Trade-off.** Execution isn't assertion: a test can run the code and assert nothing. Mutation-based strength (M6, and in the eval via reference mutants) closes that gap. Stated in limitations.

## ADR-011 Never execute anything the model supplies

**Decision.** The only process the server starts is `test_command` from `.reqtrace.yaml`, as an argv list, no shell, cwd pinned to the root, with a timeout. Paths are resolved and checked against the root. No tool takes a command or arbitrary path outside the root.
**Trade-off.** Running the repo's own tests still executes repo code; that's inherent and documented. Eval runs go in a container.
