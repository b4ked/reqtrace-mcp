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

## ADR-012 Eval runs on the user's Claude plan, isolated by HOME and environment

**Context.** `claude -p --bare` (the clean option planned in ADR-008) needs an API key; the user
asked to run on their Claude plan instead, which `--bare` cannot use.
**Decision.** No `--bare`. Each run gets a fresh, absolute `HOME`, a cleaned environment (the
hosted workspace's child-session variables removed), its own git workspace, the same prompt,
model, tools and limits in both arms, and conditions interleaved run by run. The treatment
differs only by `--plugin-dir`.
**Trade-off.** Some environment-level plugins (`cc-plugin-*`) and the browser MCP server still
load in both arms. They are identical across arms and their tools are not in the allow-list,
so they cost context but cannot act. Recorded in every run's `plugins_loaded`.

## ADR-013 Agent workspaces live outside the repository

**Context.** The pilot's first attempt put workspaces under `evals/results/`, inside the plugin
directory passed to `--plugin-dir`. Claude Code protects a loaded plugin's directory, so the
treatment arm was denied every write while the baseline was not: a harness artefact that
would have shown reqtrace "failing".
**Decision.** Workspaces and HOMEs go under `~/.cache/reqtrace-eval/` (configurable, refused if
inside the repo); only graded JSON and summaries live in `evals/results/`. All paths absolute.

## ADR-014 Validate the benchmark before trusting it

**Decision.** `python -m evals check` proves for every task that the reference passes the hidden
tests, each mutant is caught by the hidden tests of its own requirement, and the starting code
does not already pass. Grader unit tests score known-good and known-bad workspaces.
**Why it mattered.** It caught a stale-bytecode bug (two same-size mutants written in the same
second reused one `.pyc`) and a wrong expectation in a hidden test, before any agent ran.

## ADR-015 C and C++: tree-sitter to find code, clang source-based coverage to measure it

**Context.** The user asked for C/C++ support. Python's design leans on `ast` and on coverage.py's
per-test contexts; C/C++ has neither for free.
**Decision.**
- *Scanning:* tree-sitter (C and C++ grammars, MIT) parses without compiling, so it copes with
  code for other platforms and with unexpanded macros. Annotations are comments
  (`// implements:`, `// verifies:`, `// derived:`), so no header or build change is needed.
  GoogleTest `TEST*` macros parse as function definitions and become `Suite.Name` tests;
  overloads are told apart by parameter types; duplicate definitions in `#if` branches get an
  `@L<line>` suffix.
- *Coverage:* clang source-based coverage (`-fprofile-instr-generate -fcoverage-mapping`, plus
  `-fcoverage-mcdc` on clang 18 or later), read with `llvm-profdata` and `llvm-cov export`. It
  gives lines, branch outcomes and MC/DC from one build.
- *Per-test data:* each GoogleTest test runs in its own process with its own
  `LLVM_PROFILE_FILE`. A plain test executable is one test, and all test items in its source
  file share its result.
- *Build:* the repo's own build commands, from `.reqtrace.yaml`, as argv lists. reqtrace adds
  the coverage flags through `CC`, `CXX`, `CFLAGS`, `CXXFLAGS` and `LDFLAGS` (or `{coverage_flags}`
  placeholders) in a dedicated build directory.
- *One shape:* the runner writes `coverage_norm.json`, the same structure `CoverageIndex` now
  uses for Python, so status, gap and report logic is shared.

**Alternatives rejected.**
- *gcov/gcovr:* works with GCC, but MC/DC only arrived in GCC 14, and per-test data means
  resetting `.gcda` files between tests.
- *libclang:* needs a compilation database and a matching libclang; tree-sitter is a pip wheel.
- *ctags:* no reliable function extents.

**Trade-offs.**
- Clang only.
- One process per test is slower for large suites.
- Per-test coverage includes start-up code (static initialisers).
- A parser without a preprocessor can miss macro-generated functions; files it can only
  partly parse are reported.
- clang 18 measures MC/DC only for decisions of up to 6 conditions; larger ones are skipped,
  with a compiler warning in `build.log`.
- Coverage covers only code compiled for the host, so ARM-only paths need an ARM run.

**Security.** ADR-011 still holds: build and test commands come from the repo's config, never
from a tool argument, with no shell.

## ADR-016 Report implementing code no linked test executes

**Context.** On crc32c, CRC-005 (four overloads) was `VERIFIED` while one overload was never
called. The status rule asks only that *some* linked test executes *some* implementing code.
**Decision.** Keep the status rule; add an `unexercised_code` gap listing each implementing
item that no passing linked test executes. Items with no coverage data at all are labelled
"not compiled or not measured in this run" (for example ARM64 code on x86-64).
**Why not lower the status?** Status should mean the same thing in every repo. Making one
unexecuted item downgrade the requirement would make platform-specific code permanently
`WEAKLY_VERIFIED` on other hosts. The gap is reported, and not counted as blocking.
**Applies to Python too.**
