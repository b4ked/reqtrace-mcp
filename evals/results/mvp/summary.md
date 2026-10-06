### Run: 2026-10-06T12:11:15+00:00 — 10 tasks × 2 conditions × 3 run(s)

Model `claude-sonnet-5-5` · Claude Code 2.1.291 (Claude Code) · MCP SDK 2.3.0 · reqtrace `90d0d6e` · 60/60 runs graded

Means are over tasks (each task's mean over its runs). Δ = reqtrace − baseline, paired by task; 95% CI by bootstrap over tasks when ≥ 4 tasks contribute.

| Metric | baseline | reqtrace | Δ | 95% CI | tasks |
|---|---|---|---|---|---|
| Task success (pass@1) | 1.00 | 1.00 | 0.00 | [+0.00, +0.00] | 10 |
| Hidden acceptance tests passed | 1.00 | 1.00 | 0.00 | [+0.00, +0.00] | 7 |
| Verification strength (traced mutant kills) | 1.00 | 1.00 | 0.00 | [+0.00, +0.00] | 7 |
| Mutants killed by any agent test | 1.00 | 1.00 | 0.00 | [+0.00, +0.00] | 7 |
| Requirements VERIFIED (reqtrace's own check) | 0.98 | 1.00 | 0.02 | [+0.00, +0.07] | 7 |
| Test→requirement link precision | 0.52 | 0.52 | -0.00 | [-0.02, +0.03] | 7 |
| Code→requirement link precision | 0.97 | 0.97 | 0.00 | [+0.00, +0.00] | 7 |
| Code→requirement link recall | 1.00 | 1.00 | 0.00 | [+0.00, +0.00] | 7 |
| Unrequired code items (lower is better) | 0.00 | 0.00 | 0.00 | [+0.00, +0.00] | 7 |
| Agent tests that fail on correct code (lower is better) | 0.14 | 0.00 | -0.14 | [-0.43, +0.00] | 7 |
| Shipped a test failing on correct code (lower is better) | 0.14 | 0.00 | -0.14 | [-0.43, +0.00] | 7 |
| Agent ran its own tests | 0.00 | 0.53 | 0.53 | [+0.27, +0.80] | 10 |
| Agent called any reqtrace tool | 0.00 | 0.53 | 0.53 | [+0.27, +0.80] | 10 |
| Seeded defects found | 1.00 | 1.00 | 0.00 | — | 2 |
| False-positive defect findings (lower is better) | 0.00 | 0.00 | 0.00 | — | 3 |
| Requirement conflict flagged | 1.00 | 1.00 | 0.00 | — | 1 |
| Edited files during review (should be 0) (lower is better) | 0.00 | 0.00 | 0.00 | — | 3 |
| All runs succeed (pass^k) | 1.00 | 1.00 | — | — | — |

| Cost (mean per run) | baseline | reqtrace |
|---|---|---|
| Cost per run, list-price USD | 0.12 | 0.15 |
| Turns | 6.63 | 10.23 |
| Wall-clock seconds | 24.98 | 27.71 |
| Tool calls | 5.63 | 8.77 |
| reqtrace tool calls | 0.00 | 1.67 |

**Per task** (mean over runs; sd in brackets when > 1 run)

| Task | Type | baseline success | reqtrace success | baseline strength / defects | reqtrace strength / defects | baseline $ | reqtrace $ |
|---|---|---|---|---|---|---|---|
| T01-battery-implement | implement | 1.00 | 1.00 | 1.00 | 1.00 | 0.14 (0.01) | 0.17 (0.01) |
| T02-arm-implement | implement | 1.00 | 1.00 | 1.00 | 1.00 | 0.13 (0.01) | 0.18 (0.02) |
| T03-thruster-implement | implement | 1.00 | 1.00 | 1.00 | 1.00 | 0.13 (0.01) | 0.17 (0.01) |
| T04-depth-implement | implement | 1.00 | 1.00 | 1.00 | 1.00 | 0.14 (0.01) | 0.18 (0.01) |
| T05-arm-change | change | 1.00 | 1.00 | 1.00 | 1.00 | 0.11 (0.01) | 0.14 (0.01) |
| T06-battery-change | change | 1.00 | 1.00 | 1.00 | 1.00 | 0.10 (0.00) | 0.11 (0.00) |
| T07-thruster-review-boundary | review | 1.00 | 1.00 | 1.00 | 1.00 | 0.10 (0.00) | 0.11 (0.00) |
| T08-depth-review-unrequired | review | 1.00 | 1.00 | 1.00 | 1.00 | 0.11 (0.00) | 0.12 (0.00) |
| T09-battery-review-clean | review | 1.00 | 1.00 | — | — | 0.09 (0.00) | 0.10 (0.00) |
| T10-depth-ambiguity | ambiguity | 1.00 | 1.00 | 1.00 | 1.00 | 0.15 (0.00) | 0.21 (0.06) |
