# Verification evidence report

- Generated: 2026-10-06T16:33:28+00:00
- Repository revision: `578587b (uncommitted changes)`
- Test run: `20261006T163319Z-4269b1`
- Tool: reqtrace-mcp 0.1.0

## Summary

**7 of 8 requirements verified** (0 also signed off by a human). Open gaps: 9. Unrequired code items: 0.

| Status | Count |
|---|---|
| 🟠 NOT_VERIFIED | 1 |
| 🟢 VERIFIED | 7 |

## Requirements

| Req | Status | Implemented by | Verified by | Results | Stmt cov | Branch cov | MC/DC |
|---|---|---|---|---|---|---|---|
| **CRC-001** CRC-32C value of a buffer | 🟢 VERIFIED | `include/crc32c/crc32c.h::crc32c::Crc32c(const uint8_t*, size_t)`<br>`src/crc32c.cc::crc32c::Extend` | `src/crc32c_extend_unittests.h::ExtendTest.StandardResults`<br>`src/crc32c_unittest.cc::Crc32CTest.Crc32c` | passed | 89% | 50% | n/a |
| **CRC-002** Incremental computation | 🟢 VERIFIED | `src/crc32c.cc::crc32c::Extend` | `src/crc32c_extend_unittests.h::ExtendTest.BufferSlicing`<br>`src/crc32c_extend_unittests.h::ExtendTest.HelloWorld`<br>`src/crc32c_extend_unittests.h::ExtendTest.LargeBufferSlicing` | passed | 83% | 50% | n/a |
| **CRC-003** Empty input | 🟠 NOT_VERIFIED | `src/crc32c.cc::crc32c::Extend` | — | — | 83% | 50% | n/a |
| **CRC-004** C API | 🟢 VERIFIED | `src/crc32c.cc::crc32c::crc32c_extend`<br>`src/crc32c.cc::crc32c::crc32c_value` | `src/crc32c_capi_unittest.c::main` | passed | 100% | n/a | n/a |
| **CRC-005** Convenience overloads | 🟢 VERIFIED | `include/crc32c/crc32c.h::crc32c::Crc32c(const char*, size_t)`<br>`include/crc32c/crc32c.h::crc32c::Crc32c(const std::byte*, size_t)`<br>`include/crc32c/crc32c.h::crc32c::Crc32c(const std::string&)`<br>`include/crc32c/crc32c.h::crc32c::Crc32c(const std::string_view&)` | `src/crc32c_unittest.cc::CRC32CTest.Crc32cCharPointer`<br>`src/crc32c_unittest.cc::CRC32CTest.Crc32cStdString`<br>`src/crc32c_unittest.cc::CRC32CTest.Crc32cStdStringView` | passed | 79% | n/a | n/a |
| **CRC-006** Hardware acceleration with identical results | 🟢 VERIFIED | `src/crc32c.cc::crc32c::Extend`<br>`src/crc32c_arm64.cc::crc32c::ExtendArm64`<br>`src/crc32c_arm64_check.h::crc32c::CanUseArm64Crc32`<br>`src/crc32c_portable.cc::crc32c::ExtendPortable`<br>`src/crc32c_sse42.cc::crc32c::ExtendSse42`<br>`src/crc32c_sse42_check.h::crc32c::CanUseSse42()@L25`<br>`src/crc32c_sse42_check.h::crc32c::CanUseSse42()@L39` | `src/crc32c_extend_unittests.h::ExtendTest.BufferSlicing`<br>`src/crc32c_extend_unittests.h::ExtendTest.HelloWorld`<br>`src/crc32c_extend_unittests.h::ExtendTest.LargeBufferSlicing`<br>`src/crc32c_extend_unittests.h::ExtendTest.StandardResults` | passed | 83% | 78% | 0% |
| **CRC-007** Little-endian loads | 🟢 VERIFIED | `src/crc32c_read_le.h::crc32c::ReadUint16LE`<br>`src/crc32c_read_le.h::crc32c::ReadUint32LE`<br>`src/crc32c_read_le.h::crc32c::ReadUint64LE` | `src/crc32c_read_le_unittest.cc::Crc32CReadLETest.ReadUint16LE`<br>`src/crc32c_read_le_unittest.cc::Crc32CReadLETest.ReadUint32LE`<br>`src/crc32c_read_le_unittest.cc::Crc32CReadLETest.ReadUint64LE` | passed | 100% | n/a | n/a |
| **CRC-008** Alignment helper | 🟢 VERIFIED | `src/crc32c_round_up.h::crc32c::RoundUp(uintptr_t)`<br>`src/crc32c_round_up.h::crc32c::RoundUp(const uint8_t*)` | `src/crc32c_round_up_unittest.cc::CRC32CRoundUpTest.RoundUpPointer`<br>`src/crc32c_round_up_unittest.cc::CRC32CRoundUpTest.RoundUpUintptr` | passed | 100% | n/a | n/a |

## Requirement text

**CRC-001** CRC-32C value of a buffer — The library shall compute the CRC-32C (Castagnoli) checksum of a byte buffer: polynomial 0x1EDC6F41, reflected input and output, initial value and final XOR 0xFFFFFFFF.
  - acceptance: 32 bytes of 0x00 -> 0x8A9136AA (RFC 3720 B.4)
  - acceptance: 32 bytes of 0xFF -> 0x62A8AB43 (RFC 3720 B.4)
  - acceptance: bytes 0x00, 0x01, ..., 0x1F -> 0x46DD794E (RFC 3720 B.4)
  - acceptance: bytes 0x1F, 0x1E, ..., 0x00 -> 0x113FDB5C (RFC 3720 B.4)
  - acceptance: ASCII "123456789" -> 0xE3069283 (the standard CRC-32/ISCSI check value)

**CRC-002** Incremental computation — Extending the CRC of buffer A with buffer B shall give the CRC of A followed by B, for every split point, so data can be checksummed in pieces.
  - acceptance: Extend(Crc32c("hello "), "world") == Crc32c("hello world")
  - acceptance: every split of a 48-byte buffer into up to three pieces gives the whole-buffer CRC

**CRC-003** Empty input — The CRC of an empty buffer shall be 0, and extending any CRC with zero bytes shall return that CRC unchanged.
  - acceptance: Crc32c(data, 0) == 0
  - acceptance: Extend(0x12345678, data, 0) == 0x12345678

**CRC-004** C API — The C functions crc32c_value and crc32c_extend shall return the same results as the C++ functions Crc32c and Extend.
  - acceptance: crc32c_value gives the CRC-001 vectors
  - acceptance: crc32c_extend(crc32c_value("hello "), "world") == crc32c_value("hello world")

**CRC-005** Convenience overloads — The C++ overloads taking const char*, std::string, std::string_view and std::byte* shall return the same CRC as the uint8_t* form for the same bytes.
  - acceptance: each overload gives the CRC-001 vectors

**CRC-006** Hardware acceleration with identical results — The library shall use the CPU's CRC32C instructions (SSE4.2 on x86-64, the CRC32 extension on ARM64) when the CPU supports them, and a portable implementation otherwise. Every implementation shall return the same results.
  - acceptance: portable, SSE4.2 and ARM64 implementations each give the CRC-001 and CRC-002 results
  - acceptance: on a CPU without the instructions, the portable implementation is used

**CRC-007** Little-endian loads — The 16-, 32- and 64-bit loads used by the implementations shall read memory as little-endian regardless of the host's byte order.
  - acceptance: bytes 78 56 34 12 read as a 32-bit value -> 0x12345678
  - acceptance: 16-bit and 64-bit loads follow the same rule

**CRC-008** Alignment helper — Rounding a pointer or integer up to an N-byte boundary (N a power of two) shall return the smallest multiple of N that is not less than the input.
  - acceptance: RoundUp<4>(5) == 8, RoundUp<4>(8) == 8

## Open gaps

- **uncovered_branch** CRC-001 `src/crc32c.cc:22:7 false`: 1 branch(es) in implementing code never taken by any test → Add a test for the untaken branch, or remove dead code.
- **uncovered_branch** CRC-002 `src/crc32c.cc:22:7 false`: 1 branch(es) in implementing code never taken by any test → Add a test for the untaken branch, or remove dead code.
- **untested** CRC-003 `requirements/crc32c.yaml:34`: CRC-003: NOT_VERIFIED → Write tests with `// verifies: CRC-003` above each TEST(...) (or above `main` of a test executable) that check each acceptance criterion, including boundaries.
- **unexercised_code** CRC-005 `include/crc32c/crc32c.h::crc32c::Crc32c(const std::byte*, size_t)`: No passing test linked to CRC-005 executes include/crc32c/crc32c.h::crc32c::Crc32c(const std::byte*, size_t) → Add a test linked to CRC-005 that calls it, or fix the `implements` link. Code not built on this platform needs verifying on one where it is.
- **uncovered_branch** CRC-006 `src/crc32c.cc:22:7 false, src/crc32c_sse42.cc:182:10 true, src/crc32c_sse42.cc:185:21 true, src/crc32c_sse42.cc:185:21 false, src/crc32c_sse42.cc:209:10 true`: 9 branch(es) in implementing code never taken by any test → Add a test for the untaken branch, or remove dead code.
- **unexercised_code** CRC-006 `src/crc32c_arm64.cc::crc32c::ExtendArm64 (no coverage data: not compiled or not measured in this run), src/crc32c_arm64_check.h::crc32c::CanUseArm64Crc32 (no coverage data: not compiled or not measured in this run), src/crc32c_sse42_check.h::crc32c::CanUseSse42()@L25 (no coverage data: not compiled or not measured in this run)`: No passing test linked to CRC-006 executes src/crc32c_arm64.cc::crc32c::ExtendArm64 (no coverage data: not compiled or not measured in this run); src/crc32c_arm64_check.h::crc32c::CanUseArm64Crc32 (no coverage data: not compiled or not measured in this run); src/crc32c_sse42_check.h::crc32c::CanUseSse42()@L25 (no coverage data: not compiled or not measured in this run) → Add a test linked to CRC-006 that calls it, or fix the `implements` link. Code not built on this platform needs verifying on one where it is.
- **uncovered_condition** CRC-006 `src/crc32c_sse42_check.h:41:10 condition 1/2, src/crc32c_sse42_check.h:41:10 condition 2/2`: 2 condition(s) in implementing code never shown to independently affect their decision (MC/DC) → Add test cases where only that condition changes and the outcome changes with it, or simplify the decision.
- **requirement_quality** CRC-003 `requirements/crc32c.yaml:34`: [warning] More than one 'shall': consider splitting so each requirement is verified separately → Clarify the requirement, or flag it for a human.
- **requirement_quality** CRC-006 `requirements/crc32c.yaml:63`: [warning] More than one 'shall': consider splitting so each requirement is verified separately → Clarify the requirement, or flag it for a human.

## Unrequired code

None.

## Agent-suggested links (not trusted until a human accepts them)

None.

## Requirement issues raised

None.

## Review ledger (append-only)

No reviews recorded.

---

*This report is generated by reqtrace-mcp, an open-source tool inspired by public software-assurance practice (requirements traceability, independent verification, structural coverage). It is not a qualified tool and this report does not by itself satisfy any certification objective.*
