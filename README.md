# reqtrace-mcp

**Make Claude Code prove its work.** An MCP server and Claude Code plugin that traces every change
to a requirement and every requirement to a test that *actually exercises it*. It adds an
independent reviewer that can't edit code and a sign-off that only a human can give. A benchmark
measures whether any of this helps.

> Writing software is getting cheap; trusting it isn't.

Built with Claude Code. Inspired by public safety-critical practice (DO-178C-style
traceability, independence and structural coverage). It is **not** a qualified tool and makes
no certification claim. All examples are synthetic.

**Status:** M0–M4 complete: library, server, plugin and a 60-run benchmark. The headline
result is honest and mixed; see [Results](#results-10-tasks--2-arms--3-runs-claude-sonnet-55).
**Languages:** Python (pytest) and C/C++ (GoogleTest or plain test executables, clang
coverage with MC/DC), tested on a real library: [google/crc32c](#real-codebase-googlecrc32c).

---

## What it does

```
requirements/*.yaml ──► # implements: REQ-001 ──► @pytest.mark.verifies("REQ-001") ──► run under coverage
                                                                                          │
         human sign-off ◄── evidence report ◄── independent verifier ◄── gaps ◄──────────┘
```

| Status | Meaning |
|---|---|
| `NOT_IMPLEMENTED` | No code says it implements the requirement |
| `NOT_VERIFIED` | No test says it verifies it |
| `FAILING` | A linked test fails |
| **`WEAKLY_VERIFIED`** | Linked tests pass but **never execute the implementing code** (per-test coverage) |
| `VERIFIED` | Linked tests pass and execute the implementing code |
| `REVIEWED` | Verified, and a human approved this exact content (a sign-off goes stale if the code changes) |

Gap analysis also finds:

- **code no requirement asked for**;
- **implementing functions that no linked test calls** (for example one overload of four);
- dangling links;
- uncovered branches, and in C/C++ **MC/DC conditions** never shown to matter on their own;
- stale reviews, and results that are stale since the last test run. Change impact
maps a git diff to the affected requirements, the tests to rerun, and the reviews it
invalidates. Requirement text edits and deleted functions are included.

### Why the design choices matter

- **Human-only sign-off, enforced by protocol.** `record_review` is marked
  `anthropic/requiresUserInteraction`, so Claude Code prompts on every call, in every permission
  mode. The reviewer's name and rationale come from the human by MCP elicitation. They are
  never tool arguments, so the model can't fill them in.
- **Separation of duties.** The `independent-verifier` sub-agent has no Edit, Write or Bash
  tools, and judges code against requirement text only.
- **Deterministic server.** It never calls an LLM. Every output can be reproduced and audited.
- **Safe by construction.** The server only starts the repo's own tests (`coverage run -m
  pytest`, or the C/C++ build and test binaries named in `.reqtrace.yaml`), as argv lists
  built from config with no shell. No tool accepts a command. Paths are confined to the repo.

See [`docs/DECISIONS.md`](docs/DECISIONS.md) for the trade-offs behind each choice.

## Quickstart

Needs Python 3.10+ and [uv](https://docs.astral.sh/uv/). For Python repos: `pytest` and
`coverage` in the target repo's environment. For C/C++ repos: clang and LLVM tools.

**As a Claude Code plugin** (server, skill, sub-agents and commit gate):

```bash
claude plugin marketplace add hishanparry/reqtrace-mcp   # once published on GitHub
claude plugin install reqtrace@reqtrace-mcp
```

Or, without installing, from a clone: `claude --plugin-dir /path/to/reqtrace-mcp`.

**As a plain MCP server** for any MCP client: run `uvx --from /path/to/reqtrace-mcp reqtrace-mcp`
over stdio.

**As a CLI**, for humans and CI:

```bash
pip install -e .
cd examples/altitude-alerter
reqtrace verify && reqtrace matrix && reqtrace gaps
reqtrace review ALT-001 --approve --reviewer "Your Name" --rationale "Checked boundaries"
reqtrace report            # .reqtrace/evidence/evidence.md
reqtrace gate --verify     # exit 1 if gaps exceed .reqtrace.yaml thresholds
```

**For C or C++**, set `language: cpp` in `.reqtrace.yaml` and give the build commands and test
binaries. reqtrace builds with clang coverage flags itself, in its own build directory:

```yaml
language: cpp
source_dirs: [src, include]
build:
  commands:
    - [cmake, -S, ., -B, "{build_dir}", -G, Ninja, -DBUILD_TESTING=ON]
    - [cmake, --build, "{build_dir}"]
tests:
  - {binary: "{build_dir}/my_tests", kind: gtest}                        # one process per test
  - {binary: "{build_dir}/c_api_test", kind: exe, source: tests/c_api_test.c}  # exit code
```

Annotate with comments: `// implements: REQ-001` above a function, and `// verifies: REQ-001`
above a `TEST(...)` or a test `main`. This needs clang and LLVM tools (`llvm-profdata`,
`llvm-cov`); MC/DC needs clang 18 or later.

The Python example repo seeds one of each problem. Without changing anything you get one VERIFIED,
one WEAKLY_VERIFIED (a tagged test that only checks a constant), one untested and one
unimplemented requirement, plus one unrequired function.

## MCP surface

**Tools:** `list_requirements`, `get_requirement`, `trace_matrix`, `find_gaps`,
`impact_of_change`, `run_verification`, `coverage_report`, `lint_requirements`,
`flag_requirement_issue`, `propose_links` (stored as *unconfirmed*), `record_review`
(human-only) and `evidence_report`. All return structured output; read-only tools are annotated.

**Resources:** `reqtrace://requirements`, `reqtrace://requirements/{id}`, `reqtrace://matrix`,
`reqtrace://evidence/latest`.

**Prompts:** `implement_traceably`, `independent_review`.

Built on the official Python SDK 2.x and the stateless 2026-07-28 protocol. Tested with both
2026 and 2025-era clients.

## The benchmark

`evals/` asks whether Claude Code produces **more trustworthy** work with reqtrace than
without. Both arms get the same repo, prompt, model, tools and a `CONTRIBUTING.md` describing
the annotation convention. The only difference is the plugin.

- **10 tasks** in four invented domains: battery controller, robot joint limits, thruster
  limiter and ROV depth alarm.
  - 4 implement tasks.
  - 2 requirement-change tasks.
  - 3 review tasks: one boundary defect, one missing requirement plus an unrequired
    "maintenance mode" that silences the alarm, and one clean control.
  - 1 task with conflicting requirements.
- **Deterministic graders.** Hidden acceptance tests. **Verification strength**: the agent's
  tests are run against a reference implementation and against one mutant per requirement,
  and a requirement counts only if a test *linked to it* catches its mutant. Link
  precision and recall. Unrequired code. Seeded-defect detection and false positives. Whether
  the conflict was flagged. Cost.
- **Validated before use.** `python -m evals check` proves that each reference passes, that
  each mutant is caught by its own requirement's hidden tests, and that the starting code
  fails. The grader has its own tests.

```bash
python -m evals check
python -m evals run --runs 3 --out evals/results/mvp
python -m evals report evals/results/mvp
```

### Results (10 tasks × 2 arms × 3 runs, Claude Sonnet 5.5)

![results](evals/results/mvp/summary.png)

**On this benchmark, reqtrace did not measurably improve the work, and it cost 23% more per
run (54% more turns).** Sonnet 5.5 alone solved every task in every run:

- all hidden tests passed;
- every seeded defect was found, with no false positives;
- the requirement conflict was flagged.

That left nothing for a tool to improve.

The one difference is behaviour. **With reqtrace the agent ran its own tests in 16/30 runs;
without it, 0/30.** In one task, all three baseline runs shipped a test that fails against
correct code. Part of that gap comes from the strict permission setup, so it is not a clean
win.

The plugin was also never used in review tasks (0/9 runs), and the independent verifier was
never chosen unprompted.

Method, caveats, failure analysis and next steps: **[RESULTS.md](RESULTS.md)**.

## Real codebase: google/crc32c

The C/C++ support was tested on [google/crc32c](https://github.com/google/crc32c), a CRC-32C
library with portable, SSE4.2 and ARM64 implementations, GoogleTest typed tests and a C test
program. I wrote 8 requirements from RFC 3720 and the public API, and added 34 comment lines
of annotations to upstream files. Build files were unchanged.

**On the upstream tests** (22 passing), reqtrace found:

- no test of empty input;
- one of four convenience overloads never called;
- the two widest SSE4.2 loops never executed: they need 4,080+ bytes, and the largest test
  buffer is 2,048;
- the portable fallback and the CPU-feature probe unreachable on an SSE4.2 machine (MC/DC 0%);
- ARM64 code not compiled on x86-64.

**Claude Code with the plugin** (one run, no general shell) then:

- added six tests;
- left the hardware-dependent gaps open, with the right reasons;
- found an untested acceptance criterion that reqtrace can't see.

**A one-bit error** in either SSE4.2 lookup table passes all 22 upstream tests and fails the
agent's new test. That is a test gap, not a bug: the tables are correct.

Full write-up, reproduction script and raw output:
**[examples/crc32c-case-study](examples/crc32c-case-study/README.md)**.

## Limitations, honestly

- Python (pytest) and C/C++ (GoogleTest or plain executables) only. Links are at function
  level, not per acceptance criterion: an untested criterion inside a tested requirement is
  invisible to the tool.
- C/C++:
  - clang only (no GCC/gcov, no MSVC);
  - coverage only covers code compiled on the host;
  - each test runs in its own process, which is slow for very large suites;
  - per-test coverage includes start-up code;
  - plain test executables report one result for everything in them;
  - the scanner doesn't run the preprocessor, so macro-generated functions can be missed;
  - clang 18 measures MC/DC only for decisions of up to 6 conditions.
- Annotations are claims. reqtrace checks them with per-test coverage, but *execution is not
  assertion*: a test can run code and check nothing. The benchmark measures that with mutants.
  Mutation testing inside the tool is future work.
- `requiresUserInteraction` is a Claude Code hint. Other MCP clients may not honour it,
  though elicitation still keeps the reviewer's identity away from the model.
- The commit gate only sees commits Claude makes. `reqtrace gate --verify` works as a normal
  git pre-commit hook for humans.
- Benchmark: small synthetic tasks, and the model hit the ceiling. Showing a benefit on
  correctness needs harder tasks and a permission ablation. Both are planned in
  [RESULTS.md](RESULTS.md).
- The skill doesn't yet trigger on review or requirement-change prompts.

## Repo layout

```
src/reqtrace_mcp/   core library (no MCP dependency), CLI, MCP server, pytest plugin,
                    C/C++ scanner (tree-sitter) and runner (clang coverage)
skills/ agents/ hooks/ .claude-plugin/   Claude Code plugin
examples/altitude-alerter/   demo repo with one of each gap
examples/crc32c-case-study/  C++ case study on google/crc32c (setup script, results, agent run)
evals/              benchmark: domains, tasks, harness, graders, results
docs/               SPEC, DECISIONS (ADRs), DEVLOG
```

Licence: Apache-2.0.
