# Agent run: Claude Code + reqtrace on crc32c

One headless Claude Code session, run on 2026-10-06 with `run_agent.py`. This is a single run,
so it shows what can happen. It is not a measured rate.

| | |
|---|---|
| Model | `claude-sonnet-5-5` |
| Claude Code | 2.1.291, plugin loaded with `--plugin-dir` |
| Permissions | `dontAsk`; allowed: Read, Edit, Write, Glob, Grep, TodoWrite, Agent, Skill, reqtrace tools, and Bash only for read-only git (`git diff/log/show/status`). **No general shell**, so building and running the C++ tests was only possible through `run_verification` |
| Result | success, 27 turns, 87 s, $0.39 at list price (charged to plan usage) |
| reqtrace calls | 7: `list_requirements`, `lint_requirements`, `run_verification` ×2, `find_gaps` ×2, `coverage_report` |
| Skill | the agent loaded `traceable-development` without being asked |
| Files changed | `src/crc32c_extend_unittests.h`, `src/crc32c_unittest.cc` (tests only, +99/−1): [`after/agent_tests.patch`](after/agent_tests.patch) |

## What the agent did

1. Loaded the skill. Listed and linted the requirements. Ran verification (22 tests passed).
2. `find_gaps` and `coverage_report`.
3. Tried one compound shell command to look at files, which was refused. It then read the dispatcher,
   the SSE4.2 code, the CPU check and the existing tests.
4. Added six tests:

   | Test | Links | Closes |
   |---|---|---|
   | `ExtendTest.CheckValue` (typed: portable, SSE4.2, API) | CRC-001, CRC-006 | "123456789" → 0xE3069283, an acceptance criterion with no test |
   | `ExtendTest.EmptyInput` (typed) | CRC-003, CRC-006 | CRC-003 had no tests |
   | `ExtendTest.LargeBufferAgainstBitwiseReference` (typed) | CRC-001, CRC-002, CRC-006 | 70,000-byte buffer at 8 alignments, whole and split, against a bit-by-bit CRC written in the test. Reaches the SSE4.2 block loops no test reached |
   | `CRC32CTest.Crc32cBytePointer` | CRC-005 | the `std::byte*` overload no test called |
   | `CRC32CTest.Crc32cCheckValue` | CRC-001, CRC-005 | check value through the string overload |
   | `CRC32CTest.EmptyInput` | CRC-003 | empty input through the public API |

5. Ran verification again (34 passed) and `find_gaps`.

## What it said was still open

Quoted from its summary, shortened:

- The portable fallback in `Extend` can't run on a CPU with SSE4.2. Testing it needs another
  CPU, or a change to the library or build, which was out of scope.
- `CanUseSse42`'s false branches and MC/DC conditions can't be reached on this CPU. The MSVC
  variant isn't built on Linux.
- The ARM64 code isn't compiled on x86-64.
- So CRC-006's "on a CPU without the instructions, the portable implementation is used" is
  not demonstrated here.
- The two lint warnings are a decision for a human. Nothing is signed off.

All of this matches the tool's output when re-run independently.

## Checked independently

- **Re-ran reqtrace** in the agent's workspace with a clean build: 34 passed, every
  requirement VERIFIED. The remaining gaps are exactly the ones the agent listed:
  [`after/gaps.txt`](after/gaps.txt).
- **Read the diff.** The tests are real checks, not padding. The large-buffer test computes
  its expected value independently, instead of trusting the code under test.
- **Mutation check.** Do the new tests catch faults the old ones missed? See
  [`mutation.md`](mutation.md).

## What reqtrace contributed, and what the agent contributed

- **From reqtrace's output:** CRC-003 had no tests; the `std::byte*` overload was never
  executed; the SSE4.2 lines and branches were never taken; the dispatcher's fallback and the
  CPU probe can't be covered on this machine.
- **From the agent reading the requirement text:** the "123456789" check value had no test.
  reqtrace links tests to requirements, not to individual acceptance criteria, so it could
  not report this.
