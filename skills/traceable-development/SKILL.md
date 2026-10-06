---
name: traceable-development
description: Implement, change or review code against written requirements with traceability and evidence. Use when a repo has requirements (a requirements/ folder or .reqtrace.yaml), when asked to implement or verify a requirement such as REQ-012, or when asked for proof that code meets its spec.
---

# Traceable development

Work so that a human reviewer can check every claim you make. The reqtrace MCP tools compute
the facts; you do the engineering. Never mark your own work as signed off.

## The rules

1. **Every change traces to a requirement.** Put `# implements: REQ-ID` on the line directly
   above each function or class that implements it (above any decorators). Supporting helpers
   that no requirement asks for either get `# implements:` for the requirement they serve, or
   `# derived: <why it exists>` so a human can review them.
2. **Every requirement traces to a test that really checks it.** Mark tests
   `@pytest.mark.verifies("REQ-ID")`. Cover each acceptance criterion, both sides of every
   boundary, and every branch in the implementing code. A test only counts if it *calls* the
   implementing code: reqtrace marks tagged tests that never execute it as `WEAKLY_VERIFIED`.
3. **Build only what is required.** Extra features show up as `unrequired_code`. If you think
   something extra is needed, flag it; don't add it.
4. **Don't guess at unclear requirements.** If a requirement is ambiguous, conflicts with
   another, or can't be tested, call `flag_requirement_issue` (kind `ambiguous`, `conflict`,
   `untestable` or `incomplete`, naming related requirement ids) and tell the user. Implement
   only what is unambiguous.
5. **Never weaken a test to make it pass.** If a test that matches the requirement fails, the
   code is wrong, or the requirement is, and that's an issue to flag.

### In C and C++ (`language: cpp` in `.reqtrace.yaml`)

Same rules, comment syntax instead of decorators:

```cpp
// implements: CRC-001
uint32_t Extend(uint32_t crc, const uint8_t* data, size_t n) { ... }

// derived: lookup-table builder, no parent requirement
static void BuildTable() { ... }

// verifies: CRC-001, CRC-006
TEST(ExtendTest, StandardVectors) { ... }   // also TEST_F, TEST_P, TYPED_TEST(_P)
```

`/* ... */` works too, as does a trailing comment on the definition line. For a plain test
executable (exit 0 = pass), put `// verifies:` above its `main`. Don't edit build files to add
coverage flags: `run_verification` builds with clang coverage itself. C/C++ gaps can also
include `uncovered_condition` (MC/DC: a condition never shown to change its decision on its
own) and `unexercised_code` (an implementing function, such as one overload, that no linked
test calls).

## Workflow

1. `list_requirements` and `lint_requirements`. Read the requirements you are working on with
   `get_requirement`. Flag problems now (rule 4).
2. If you are changing existing code, run `impact_of_change` after editing to see which
   requirements and tests your change touches, and update those tests.
3. Implement with annotations (rules 1 and 3).
4. Write or update tests (rule 2).
5. `run_verification`. Then `find_gaps` and fix, in this order: `failing`, `weakly_verified`,
   `untested`, `unimplemented`, `unexercised_code`, `uncovered_branch`,
   `uncovered_condition`, `unrequired_code`, `dangling_link`.
   Repeat until `find_gaps` reports `clean: true`, or until only items needing a human remain
   (open issues, unconfirmed suggestions, reviews).
6. If you have the `independent-verifier` agent, ask it to review the requirements you
   touched. Fix real findings; argue with wrong ones in your summary, don't silently ignore them.
7. `evidence_report`, then summarise for the user: what is verified, what is not, open issues,
   and that the report at `.reqtrace/evidence/evidence.md` is ready for their review.
8. Only call `record_review` if the user asks you to start sign-off. It asks *them* for their
   name and rationale; you cannot fill those in.

## Reviewing instead of implementing

When asked to review or verify code (not change it), don't edit source files. Judge the code
against the requirement text and acceptance criteria only. Report each finding with
requirement id, kind (`defect`, `missing_requirement`, `untested_behaviour`, `weak_test`,
`unrequired_code`, `requirement_issue`), file, line and a one-line description. If the task
says where findings go (for example a `FINDINGS.json` file), write them there. If you find
nothing wrong, say so plainly; don't invent findings.

## If the tools are unavailable

The convention still applies: annotate, mark tests, run the tests yourself (`pytest`, or the
repo's own C/C++ test command), and state in your summary which requirements have passing
linked tests.
