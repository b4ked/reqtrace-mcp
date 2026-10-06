# Case study: reqtrace on a real C++ library (google/crc32c)

[google/crc32c](https://github.com/google/crc32c) computes the CRC-32C checksum used by
iSCSI, SCTP and many storage systems. It has:

- a portable implementation, plus SSE4.2 and ARM64 hardware implementations chosen at run
  time;
- a C API alongside the C++ API;
- GoogleTest tests, including typed tests that run the same cases against each
  implementation;
- a plain C test program.

It is small enough to read in an afternoon, and real enough to test the C/C++ support
properly. Pinned commit: `2bbb3be` (BSD-3-Clause; see [NOTICE](NOTICE)).

**What was added to the upstream code:** 34 comment lines in upstream files
([`annotations.patch`](annotations.patch)), plus two new files: the config and the requirements. The tool supplies the build flags itself: no
build file was edited.

## Run it yourself

You need git, CMake, Ninja, clang and the LLVM tools (`llvm-profdata`, `llvm-cov`). MC/DC
needs clang 18 or later.

```bash
pip install -e ../..                 # reqtrace, from the repo root
./setup.sh /tmp/crc32c               # clone at the pinned commit, add config, apply annotations
cd /tmp/crc32c
reqtrace verify                      # build with clang coverage, run each test alone (about 20 s)
reqtrace matrix && reqtrace gaps
reqtrace report                      # .reqtrace/evidence/evidence.md
```

## Inputs

- **[`requirements/crc32c.yaml`](requirements/crc32c.yaml):** 8 requirements. crc32c has no
  requirements document, so I wrote these from public sources:
  - RFC 3720 section 12.1 and appendix B.4 for the algorithm and test vectors;
  - the library's header comments and README for the API;
  - the standard CRC-32/ISCSI check value.

  Every vector was checked against an independent bit-by-bit implementation first. CRC-007
  (little-endian loads) and CRC-008 (alignment) are derived requirements, with CRC-006 as
  their parent.
- **[`.reqtrace.yaml`](.reqtrace.yaml):** the build commands, as argv lists. It also lists the
  two test binaries: `crc32c_tests` (GoogleTest) and `crc32c_capi_tests` (a C program whose
  exit code is the result). crc32c keeps its tests next to its code, so test files are
  recognised by name patterns.
- **[`annotations.patch`](annotations.patch):**
  - `// implements:` on 19 functions;
  - `// verifies:` on 14 test definitions;
  - one `// derived:` (the prefetch hint, which cannot change any result).

## Results on the upstream tests

Machine: x86-64 Linux with SSE4.2. Toolchain: clang 18.1.3. 22 tests, all passing (the 4 typed
tests run 3 times each). Full output: [`results/before/`](results/before/).

| Req | Status | Stmt | Branch | MC/DC | What reqtrace found |
|---|---|---|---|---|---|
| CRC-001 value | VERIFIED | 89% | 50% | n/a | The dispatcher's portable fallback (`crc32c.cc` line 28 in the annotated copy) never runs |
| CRC-002 incremental | VERIFIED | 83% | 50% | n/a | Same fallback |
| CRC-003 empty input | **NOT_VERIFIED** | 83% | 50% | n/a | **No test checks empty input** |
| CRC-004 C API | VERIFIED | 100% | n/a | n/a | |
| CRC-005 overloads | VERIFIED | 79% | n/a | n/a | **`Crc32c(const std::byte*, size_t)` is never called** by any test (`unexercised_code`) |
| CRC-006 hardware paths | VERIFIED | 83% | 78% | 0% | **The two widest SSE4.2 loops never run** (they need 4,080+ bytes; the largest test buffer is 2,048); ARM64 code not compiled here; the CPU probe's `false` outcomes are impossible on this CPU |
| CRC-007 LE loads | VERIFIED | 100% | n/a | n/a | |
| CRC-008 alignment | VERIFIED | 100% | n/a | n/a | |

"n/a" for MC/DC means the code has no decision with two or more conditions. CRC-006's 0% is
`__get_cpuid(1, &eax, &ebx, &ecx, &edx) && ((ecx & (1 << 20)) != 0)` in `CanUseSse42`. On a machine with SSE4.2, both
conditions are always true. Proving that each one independently changes the decision would
need a way to inject the CPU feature bits.

## Closing the gaps with Claude Code

Claude Code (Sonnet 5.5) ran with the reqtrace plugin and **no general shell** (only read-only git), so it could
only build and test through `run_verification`. It was told to close what it could using tests
only. Details: [`results/agent_run.md`](results/agent_run.md).

- **Session:** 27 turns, 87 seconds, $0.39 at list price.
- **What it added:** six tests in two existing test files ([diff](results/after/agent_tests.patch)).
  - Empty-input tests.
  - A `std::byte` overload test.
  - The "123456789" check value, which it found untested by reading the requirement text.
  - A 70 KB test across 8 alignments against a bit-by-bit reference CRC.
- **What it left open, correctly, with reasons:**
  - the portable fallback and the CPU probe, which can't be reached on this CPU;
  - ARM64, which isn't built here;
  - the lint warnings, which are for a human to decide.

**After:** 34 tests pass, and every requirement is VERIFIED. Coverage of CRC-006's implementing
code went from 83% to 99% of lines and from 78% to 92% of branches. Full output: [`results/after/`](results/after/).

**Did the new tests matter?** I changed one bit in each of the two SSE4.2 lookup tables that
the upstream tests never reached. **All 22 upstream tests still passed. The agent's
large-buffer test failed** in its SSE4.2 and public API instances, and reqtrace marked
CRC-001, -002 and -006 `FAILING`. Details: [`results/mutation.md`](results/mutation.md).

To be clear about scope:

- These are test gaps, not bugs. crc32c's tables are correct.
- This is one agent run, not a measured rate.
- Upstream may exercise these paths in ways a unit-test run doesn't see, such as benchmarks or
  other CI machines.

## What this exercise taught me about the tool

- **The status alone hides things.** CRC-005 was VERIFIED while one of its four overloads was
  never called: "a linked test executes some implementing code" is a low bar. That led to the
  `unexercised_code` gap: implementing functions that no passing linked test executes. It now
  applies to Python too.
- **Coverage only measures what was compiled.** The ARM64 implementation and the MSVC CPU
  probe have no coverage data on Linux x86-64. reqtrace now reports these as "no coverage
  data: not compiled or not measured in this run", rather than counting them as covered or
  ignoring them.
- **Requirement-level links miss acceptance criteria.** The untested check value was found by
  the agent reading the text, not by reqtrace. Linking tests to individual acceptance criteria
  would close this, at the cost of more annotation work.
- **MC/DC needs test seams for hardware-dependent decisions.** This is the kind of finding a
  DO-178C-style structural coverage review raises. reqtrace makes it visible; it can't fix it.
