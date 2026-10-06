# reqtrace-mcp — Specification (M0)

*Status: draft for review at the M0 gate. Date: 2026-10-06. Working name: `reqtrace-mcp` (see §9 for alternatives).*

This spec turns `Brief - reqtrace-mcp` into concrete formats, interfaces and an eval design. Every non-obvious choice links to an ADR in `DECISIONS.md`. Facts about MCP and Claude Code were checked against current docs on 2026-10-06 (§10); anything marked **[spike]** was also run in a sandbox.

---

## 1. One-paragraph summary

`reqtrace-mcp` is a Python MCP server, shipped as a Claude Code **plugin** (server + skill + two sub-agents + commit hook), that makes an agent prove its work. Requirements live in YAML. Code declares what it implements with a comment; tests declare what they verify with a pytest marker. The server builds a trace matrix, finds gaps (including **code that no requirement asked for**), runs the tests under coverage, and checks something plain traceability tools miss: **whether a test linked to a requirement actually executes the code that implements it**. Agents can propose links and flag ambiguous requirements, but **only a human can sign off**, enforced by the protocol, not by politeness. An eval harness measures whether Claude Code produces more trustworthy work with the plugin than without it.

## 2. Scope

**In (MVP = M0–M4):** Python target repos tested with pytest; YAML requirements; function-level trace links; statement + branch coverage; gap analysis; git-diff change impact; human review ledger; Markdown evidence report; stdio transport; skill, 2 sub-agents, commit hook; 10-task eval, 2 conditions, 3 runs each.

**Later (M5–M6):** HTML evidence report and dogfooding CI; 25–40 eval tasks; skill-only ablation; Streamable HTTP transport; `claude plugin eval` suite; mutation-based test strength.

**Out (documented as future work):** MC/DC coverage, non-Python targets, ReqIF/DOORS import, LLM calls inside the server, any compliance claim.

**Non-claims (will appear in README):** This is inspired by public DO-178C concepts (traceability, independence, structural coverage). It is not a qualified tool, does not satisfy any certification objective, and contains no material from any employer.

## 3. Data formats

### 3.1 Requirements: `requirements/*.yaml` → ADR-003

```yaml
# requirements/alerter.yaml
- id: REQ-001
  title: Low-altitude alert
  text: The alerter shall raise an alert when altitude is below the configured floor.
  rationale: Gives the operator time to react before terrain.
  acceptance:
    - altitude 499 ft with floor 500 ft -> alert
    - altitude 500 ft with floor 500 ft -> no alert
  parent: SYS-004          # optional, may point at a higher-level requirement
  tags: [safety]           # optional
```

Rules: IDs match `^[A-Z][A-Z0-9]*-\d+$` and are unique across files; `text` is required; `acceptance` is a list of strings (warned if empty). A loader error names the file and line.

### 3.2 Trace annotations → ADR-004

**Code** (zero runtime dependency in the target repo):

```python
# implements: REQ-001, REQ-002
def altitude_alert(alt_ft: float, floor_ft: float = 500.0) -> bool: ...

# derived: input clamping helper, no parent requirement (rationale required)
def _clamp(x: float) -> float: ...
```

The comment applies to the next `def` or `class`. Parsed with `tokenize` + `ast` (comments are not in the AST). A method inherits its class's links unless it has its own.

**Tests** (standard pytest marker, registered by our plugin):

```python
@pytest.mark.verifies("REQ-001")
def test_alert_just_below_floor(): ...
```

### 3.3 Project config: `.reqtrace.yaml` (optional)

```yaml
source_dirs: [src]
test_dirs: [tests]
requirements: requirements/
test_command: ["python", "-m", "pytest"]   # argv list, never a shell string
timeout_s: 300
unrequired_code: {ignore_private: true, ignore: ["**/__init__.py"]}
gate: {max_untested: 0, max_unimplemented: 0, max_unrequired: 0, max_failing: 0}
```

### 3.4 State: `.reqtrace/` (committed except `runs/`)

| File | Contents | Written by |
|---|---|---|
| `suggested_links.yaml` | Agent-proposed links, status `unconfirmed`, with code hash at proposal time | `propose_links` |
| `issues.jsonl` | Requirement problems flagged by agents (ambiguity, conflict, untestable) | `flag_requirement_issue` |
| `reviews.jsonl` | Append-only ledger: reviewer, UTC timestamp, decision, rationale, hash of reviewed code + tests | humans only (§5.4) |
| `runs/<id>/` | Test results JSON, `.coverage`, run metadata | `run_verification` |
| `evidence/` | Generated evidence pack | `evidence_report` |

Hashes make sign-off honest: a review or accepted suggestion becomes **stale** automatically when the code it covered changes.

## 4. Core library (`reqtrace_mcp.core`, no MCP dependency)

| Module | Responsibility |
|---|---|
| `model` | Pydantic models: `Requirement`, `Link`, `TestResult`, `Gap`, `Review`, `Status` |
| `requirements` | Load + validate YAML; lint (missing acceptance, duplicate IDs, dangling parent, vague words such as "fast", "appropriate", "as needed") |
| `annotations` | Scan source and tests; produce code↔req and test↔req links with file/line spans |
| `pytest_plugin` | Stdlib-only pytest plugin: registers `verifies`, writes per-test outcome + markers to JSON **[spike: JUnit XML drops markers]** |
| `runner` | Runs `test_command` under `coverage run --branch` with `dynamic_context = test_function`, in the repo's own environment, with a timeout |
| `coverage_map` | Reads `.coverage` via the `CoverageData` API to map test → executed lines **[spike: JSON report omits contexts]** |
| `matrix` | Joins everything into the trace matrix and per-requirement status |
| `impact` | `git diff` → changed line ranges → affected functions → requirements → tests to rerun; also requirement-text changes |
| `review` | Ledger read/write, hashing, staleness |
| `report` | Markdown evidence pack (HTML in M5) |
| `cli` | `reqtrace matrix|gaps|impact|verify|review|report|gate|serve` |

### 4.1 Requirement status (the heart of the tool)

Evaluated in this order; the first match wins:

| Status | Meaning |
|---|---|
| `NOT_IMPLEMENTED` | No code declares `implements` for it |
| `NOT_VERIFIED` | No test declares `verifies` for it |
| `FAILING` | At least one linked test failed or errored in the latest run |
| `WEAKLY_VERIFIED` | Linked tests pass but **none executes the implementing code** (from per-test coverage). Catches tests that are tagged but test something else |
| `VERIFIED` | Linked tests pass and execute the implementing code |
| `REVIEWED` | Verified, plus a human approval whose hashes still match |

### 4.2 Gap kinds

`unimplemented`, `untested`, `failing`, `weakly_verified`, `unrequired_code` (public function or class with neither `implements` nor `derived`), `dangling_link` (annotation names an unknown ID), `stale_review`, `stale_suggestion`, `uncovered_branch` (in implementing code), `open_issue` (flagged requirement not resolved).

## 5. MCP server

Built on the official Python SDK `mcp` 2.3.x (`MCPServer`), speaking protocol revision 2026-07-28 with automatic fallback for older clients **[spike]**. → ADR-001, ADR-002.

### 5.1 Repository root and safety → ADR-006

- Root comes from `--root`, else `CLAUDE_PROJECT_DIR` (Claude Code sets this for stdio servers), else the working directory. MCP Roots is deprecated in 2026-07-28, so we do not use it.
- Every path argument is resolved and rejected if it escapes the root (symlinks included).
- The only thing ever executed is `test_command` from config, as an argv list without a shell, with cwd = root and a timeout. No tool accepts a command.
- Errors the model should act on are raised as `ToolError` (the model sees the message); everything else is logged to stderr and returned generically **[spike]**.

### 5.2 Tools

All return structured output (Pydantic models → `outputSchema`) plus a short text summary. Read-only tools set `readOnlyHint`.

| Tool | Args | Returns | Notes |
|---|---|---|---|
| `list_requirements` | `tag?`, `status?` | requirements with status | read-only |
| `get_requirement` | `req_id` | requirement, links, tests, last results, issues, reviews | read-only |
| `trace_matrix` | — | full matrix | read-only |
| `find_gaps` | `kinds?` | gaps with locations and a suggested next action | read-only |
| `impact_of_change` | `base_ref="HEAD"`, `include_uncommitted=true` | changed functions, affected requirements, tests to rerun, reviews made stale | read-only |
| `run_verification` | `req_ids?` | run id, per-test outcomes, per-requirement status | runs repo tests (§5.1) |
| `coverage_report` | `req_id?` | statement/branch coverage of implementing code, uncovered lines/branches | read-only |
| `lint_requirements` | — | deterministic quality findings | read-only |
| `flag_requirement_issue` | `req_id`, `kind`, `description` | issue id | writes `issues.jsonl` |
| `propose_links` | list of `{req_id, kind: implements|verifies, target, rationale}` | accepted-as-unconfirmed or rejected with reason | target must exist |
| `record_review` | `req_ids`, `decision` | ledger entries | **human only, §5.4** |
| `evidence_report` | `format="md"` | path + headline numbers | writes `evidence/` |

### 5.3 Resources and prompts

Resources: `reqtrace://requirements`, `reqtrace://requirements/{req_id}`, `reqtrace://matrix`, `reqtrace://evidence/latest`. Claude Code exposes them as `@` mentions.

Prompts (Claude Code lists MCP prompts as slash commands): `implement_traceably(req_id)`, `independent_review(req_ids)`.

### 5.4 Human sign-off cannot be done by the agent → ADR-007

`record_review` is the point of the whole tool, so it gets two protections:

1. Its `tools/list` entry sets `_meta["anthropic/requiresUserInteraction"] = true`. Claude Code then shows a permission prompt on **every** call, even in `acceptEdits`, `auto` and `bypassPermissions` modes, with no "don't ask again"; allow rules cannot skip it; in `dontAsk` mode it is denied.
2. The reviewer's name and rationale are **not tool arguments**. The tool asks the human for them via elicitation (`Resolve(...)` → `Elicit`), which works on both protocol eras. The model can only nominate what to review.

Humans can also sign off without an agent: `reqtrace review REQ-001 --approve`.

## 6. Claude Code integration (one plugin) → ADR-005

```
reqtrace-mcp/
├── .claude-plugin/plugin.json      # name: reqtrace
├── .claude-plugin/marketplace.json # so the repo is installable as a marketplace
├── .mcp.json                       # server "reqtrace" → tools mcp__plugin_reqtrace_reqtrace__*
├── skills/traceable-development/SKILL.md
├── agents/req-implementer.md
├── agents/independent-verifier.md
├── hooks/hooks.json                # PreToolUse(Bash) commit gate
└── src/reqtrace_mcp/ ...           # the Python package (CLI command: reqtrace)
```

- **Skill** `traceable-development`: read requirement → lint it; flag rather than guess if ambiguous → implement with `# implements:` → write tests with `verifies`, including the acceptance boundaries → `run_verification` → close gaps until none of `unimplemented|untested|failing|weakly_verified|unrequired_code` → `evidence_report` → hand to `independent-verifier` → ask the human to review. Keeps `SKILL.md` under 500 lines.
- **`req-implementer`**: full edit tools + reqtrace tools.
- **`independent-verifier`**: `tools: Read, Grep, Glob` plus read-only reqtrace tools and `run_verification`. **No Edit, Write or Bash**, so it cannot change code (Bash is excluded because it could edit files). `omitClaudeMd: true` and a system prompt telling it to judge the code against requirement text only, not the implementer's explanation. Output: structured findings. Plugin agents ignore `hooks`, `mcpServers` and `permissionMode`, so the restriction relies on `tools`, which plugin agents do support.
- **Commit gate**: `PreToolUse` on `Bash`; the script reads the command from stdin JSON, and for `git commit` runs `reqtrace gate`; exit 2 blocks with the gap summary. Honest limit: it only sees commits Claude makes; the same `reqtrace gate` is offered as a git pre-commit hook for humans.

Install paths: (a) whole plugin via `/plugin marketplace add <github>/reqtrace-mcp` then `/plugin install reqtrace@reqtrace-mcp`; (b) server only: `claude mcp add reqtrace -- uvx reqtrace-mcp serve` (after PyPI publish in M6).

## 7. Eval design (the centrepiece) → ADR-008, ADR-009

### 7.1 Question

Does Claude Code produce **more trustworthy** work on requirement-driven tasks with the plugin than without it, and at what cost?

### 7.2 Fairness rules

- Both conditions get the same task prompt and the same repo, including a `CONTRIBUTING.md` that documents the annotation convention. So the baseline knows the rules; the measured difference is the tooling and workflow, not secret knowledge.
- Graders never use the agent's own claims. They re-run everything from the final workspace.
- Hidden tests and reference mutants live outside the workspace and are copied in only after the agent finishes.

### 7.3 Runner

Custom Python harness (`evals/harness/`), one command: `python -m evals run --suite mvp --runs 3`.

Per (task, condition, run): copy the task repo to a fresh temp dir → `git init` + commit → run

```
claude -p "<task prompt>" --bare --output-format stream-json --verbose \
  --model <pinned> --max-turns <task.max_turns> --permission-mode dontAsk \
  --allowedTools "Read,Edit,Write,Glob,Grep,Bash(python -m pytest *)[,mcp__plugin_reqtrace_reqtrace__*]" \
  [--plugin-dir <repo root>]          # treatment only
```

`--bare` matters: it skips the host's hooks, skills, plugins, MCP servers and CLAUDE.md, so the baseline is truly clean and the treatment differs by exactly one flag. It needs `ANTHROPIC_API_KEY`. Runs execute inside a container. The harness records Claude Code version, model ID, SDK versions and the git SHA of this repo in every result file.

Why not only `claude plugin eval`: it has no custom-code graders, so it cannot run hidden acceptance tests. We will still add a small `claude plugin eval` suite in M6 for what it is good at: whether the skill triggers on natural phrasing and whether tools run in the right order (`tool_used`, `tool_order` graders, built-in with/without Δ).

### 7.4 Task suite (MVP: 10 tasks, all invented)

| # | Type | Domain flavour | What a good answer does |
|---|---|---|---|
| 1–4 | Implement | altitude alerter; battery state machine; joint-limit checker; thruster command limiter | Implements all requirements, tests every acceptance boundary, no extras |
| 5–6 | Change | requirement edit that ripples through code and tests | Updates code, updates affected tests, nothing stale |
| 7–8 | Seeded defect review | off-by-one boundary; extra unrequired feature | Reports the planted defect precisely |
| 9 | Clean review (control) | correct code | Reports **no** defect; measures false positives |
| 10 | Ambiguity | two conflicting requirements | Flags the conflict instead of guessing |

Each task: `task.yaml` (prompt, type, max_turns, ground truth), `repo/` (what the agent sees, with stubbed function signatures so the API is fixed), `hidden/tests/`, `hidden/reference/` (correct implementation) and `hidden/mutants/` (one reference variant per requirement, each violating only that requirement).

Review and ambiguity tasks ask both conditions to write `FINDINGS.json` (`[{req_id, kind, file, line, description}]`). In the treatment, `flag_requirement_issue` also writes there, so the file is the common grading surface.

### 7.5 Metrics (all deterministic unless stated)

| Metric | How |
|---|---|
| Task success | Hidden tests pass (all) |
| Requirement coverage | % requirements with a passing, linked test, computed by re-running `reqtrace` on the final workspace |
| **Verification strength** (new) | Run the agent's tests against each reference mutant. A `verifies(REQ-k)` test "really verifies" REQ-k if it passes on the reference and fails on mutant k. Gives link precision and per-requirement detection. Possible because stubs fix the API |
| Trace accuracy | Precision/recall of `implements` links against the expected implementing functions in `task.yaml` |
| Unrequired code | Count of `unrequired_code` gaps |
| Defect detection | Planted defect matched by req_id + kind + line within ±3 lines |
| False positives | Findings matching nothing; checked against my own labels on a sample before any LLM judge is trusted |
| Ambiguity flagged | Correct req_ids present in `FINDINGS.json` |
| Cost | `total_cost_usd`, tokens, turns, wall-clock, tool calls (from stream-json) |
| Reliability | mean ± sd over runs, **pass^k** (all k runs succeed) and pass@1; paired by task; bootstrap 95% CI on the difference |

LLM-as-judge is only a fallback for matching free-text findings, and only after calibration against my labels.

### 7.6 Output

`evals/results/<timestamp>/` with raw JSON per run, `RESULTS.md` (method, table, limitations, failure analysis per task, including where the plugin did not help), and one chart (success and verification strength by condition, with CIs).

### 7.7 Budget (estimate, to confirm with a pilot)

60 runs (10 × 2 × 3). At roughly $0.30–$1.50 per run on a Sonnet-class model, about **$20–$90**. A 1-run pilot on 2 tasks comes first.

## 8. Milestone plan (fits ~2 weekends to MVP)

| Milestone | Deliverable | Rough effort |
|---|---|---|
| M1 | Core library + CLI, example repo, unit tests | 1 day |
| M2 | MCP server, error-path tests via in-memory client, plugin manifest | 0.5 day |
| M3 | Skill, 2 sub-agents, hook; one end-to-end run in Claude Code | 0.5 day |
| M4 | 10 tasks, harness, pilot, full run, first `RESULTS.md` | 1–1.5 days |
| M5 | HTML report, self-requirements, CI publishing its own evidence | 1 day |
| M6 | 25–40 tasks, skill-only ablation, `claude plugin eval` suite, README, GIF, write-up | 2 days |

## 9. Open decisions for you at this gate

1. **Name.** Recommended: keep `reqtrace-mcp` (free on PyPI; plugin name `reqtrace`). Alternatives checked free on PyPI: `traceproof`, `reqproof`, `showyourwork-mcp`. Note: a different, unrelated `reqtrace` package exists on PyPI, so our import package will be `reqtrace_mcp` to avoid a clash.
2. **Dependencies** (brief says ask first). Runtime: `mcp>=2.3,<3` (brings pydantic), `pyyaml`, `coverage`. Target repos need `pytest` + `coverage` in their own env. Dev: `pytest`, `ruff`, `mypy`. Eval extra: `matplotlib` (charts). No Jinja (stdlib templating is enough).
3. **Eval model and budget.** Recommended: `claude-sonnet-5-5` pinned for the main run, one Opus spot-check. Who supplies the API key: the eval cannot run in this workspace without one.
4. **Gate cadence.** The brief asks me to stop at every milestone. Do you want that, or should I run M1–M3 back to back and stop before the eval (M4), which is where money is spent?

## 10. Sources checked (2026-10-06)

- MCP spec 2026-07-28 changelog (stateless core, `server/discover`, roots/sampling/logging deprecated, MRTR): modelcontextprotocol.io/specification/2026-07-28/changelog
- Python SDK 2.3.0 (released 2026-10-02) and "What's new in v2" (`MCPServer`, `Client(server)` in-memory testing, `ToolError`, `Resolve`/`Elicit`): pypi.org/project/mcp, py.sdk.modelcontextprotocol.io/whats-new
- Claude Code docs: MCP (plugin tool naming, `CLAUDE_PROJECT_DIR`, `requiresUserInteraction`, output limits), skills, sub-agents (plugin agent field support), plugin components, headless (`--bare`, stream-json), plugin evals: code.claude.com/docs/en/{mcp, skills, sub-agents, plugins/components, headless, plugin-evals}
- Local spike: SDK 2.3.0, pytest 9.1.1, coverage 7.16.2, Claude Code 2.1.291
