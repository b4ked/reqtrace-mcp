# Mutation check: do the new tests catch what the old ones missed?

reqtrace reported that no test executed lines 183–220 of `src/crc32c_sse42.cc`, and that the
loop conditions on lines 182 and 209 were never true. (These are line numbers in the annotated
copy, one more than upstream.) The lines are the bodies of the two widest interleaved loops
of the SSE4.2 implementation, including the steps that combine their results.

| Loop | Runs when the remaining input is at least | Lookup table |
|---|---|---|
| block 0 | 3 × 5,440 = 16,320 bytes | `kBlock0SkipTable` |
| block 1 | 3 × 1,360 = 4,080 bytes | `kBlock1SkipTable` |

The largest buffer in the upstream tests is 2,048 bytes. So an error in either table could
pass the upstream tests.

To check, I changed one bit of one constant in each table, one mutant at a time. I then ran
the full reqtrace verification, with a clean build, on two copies:

- **before:** upstream tests plus annotations;
- **after:** the same, plus the agent's tests.

| Mutant | before: 22 upstream tests | after: 34 tests |
|---|---|---|
| `kBlock0SkipTable[0][1]`: `0xff770459` → `0xff770458` | **all 22 pass** | 2 fail: `Sse42/ExtendTest/0.LargeBufferAgainstBitwiseReference`, `Api/ExtendTest/0.LargeBufferAgainstBitwiseReference` |
| `kBlock1SkipTable[0][1]`: `0x79113270` → `0x79113271` | **all 22 pass** | the same 2 fail |

- With the mutants, reqtrace reports CRC-001, CRC-002 and CRC-006 as `FAILING` after the change,
  and `VERIFIED` before it.
- The `Portable/` instance of the new test passes both times. That is correct: the portable
  code doesn't use these tables.
- The `Api/` instance fails because on this CPU the public API dispatches to SSE4.2.

## What this does and does not show

**It shows:**

- A one-bit error in either table passes the upstream unit tests at this commit on an x86-64
  machine with SSE4.2.
- The coverage gap reqtrace reported was real.
- The test the agent wrote closes it.

**It does not show:**

- **That crc32c has a bug.** The tables are correct, and every unmutated test passes.
- **Anything about how upstream tests the library elsewhere.** For example, benchmarks
  exercise large buffers, though they don't check results.
- **The ARM64 implementation's tests.** It isn't compiled on x86-64, so it was not examined.

How it was run: each mutant is a one-character edit on a copy of each workspace (the annotated
upstream clone, and the agent's), followed by `reqtrace verify` with a fresh `.reqtrace/`:

```bash
sed -i '40s/0xff770459/0xff770458/' src/crc32c_sse42.cc   # block 0 (annotated-copy line 40)
sed -i '66s/0x79113270/0x79113271/' src/crc32c_sse42.cc   # block 1 (annotated-copy line 66)
reqtrace verify; reqtrace matrix
```
