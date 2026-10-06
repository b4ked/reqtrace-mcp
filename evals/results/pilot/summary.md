### Run: 2026-10-06T11:31:13+00:00 — 2 tasks × 2 conditions × 1 run(s)

Model `claude-sonnet-5-5` · Claude Code 2.1.291 (Claude Code) · MCP SDK 2.3.0 · reqtrace `7463c57` · 4/4 runs graded

Means are over tasks (each task's mean over its runs). Δ = reqtrace − baseline, paired by task; 95% CI by bootstrap over tasks when ≥ 4 tasks contribute.

| Metric | baseline | reqtrace | Δ | 95% CI | tasks |
|---|---|---|---|---|---|
| Task success (pass@1) | 1.00 | 1.00 | 0.00 | — | 2 |
| Hidden acceptance tests passed | 1.00 | 1.00 | 0.00 | — | 1 |
| Verification strength (traced mutant kills) | 1.00 | 1.00 | 0.00 | — | 1 |
| Mutants killed by any agent test | 1.00 | 1.00 | 0.00 | — | 1 |
| Requirements VERIFIED (reqtrace's own check) | 1.00 | 1.00 | 0.00 | — | 1 |
| Test→requirement link precision | 0.37 | 0.71 | 0.35 | — | 1 |
| Code→requirement link precision | 1.00 | 1.00 | 0.00 | — | 1 |
| Code→requirement link recall | 1.00 | 1.00 | 0.00 | — | 1 |
| Unrequired code items (lower is better) | 0.00 | 0.00 | 0.00 | — | 1 |
| Agent tests that fail on correct code (lower is better) | 0.00 | 0.00 | 0.00 | — | 1 |
| Seeded defects found | 1.00 | 1.00 | 0.00 | — | 1 |
| False-positive defect findings (lower is better) | 0.00 | 0.00 | 0.00 | — | 1 |
| Requirement conflict flagged | — | — | — | — | 0 |
| Edited files during review (should be 0) (lower is better) | 0.00 | 0.00 | 0.00 | — | 1 |
| All runs succeed (pass^k) | 1.00 | 1.00 | — | — | — |

| Cost (mean per run) | baseline | reqtrace |
|---|---|---|
| Cost per run, list-price USD | 0.12 | 0.16 |
| Turns | 5.50 | 11.00 |
| Wall-clock seconds | 23.70 | 29.85 |
| Tool calls | 4.50 | 9.50 |
| reqtrace tool calls | 0.00 | 3.00 |

**Per task** (mean over runs; sd in brackets when > 1 run)

| Task | Type | baseline success | reqtrace success | baseline strength / defects | reqtrace strength / defects | baseline $ | reqtrace $ |
|---|---|---|---|---|---|---|---|
| T01-battery-implement | implement | 1.00 | 1.00 | 1.00 | 1.00 | 0.14 | 0.20 |
| T07-thruster-review-boundary | review | 1.00 | 1.00 | 1.00 | 1.00 | 0.10 | 0.11 |
