"""C and C++ support: scanner (tree-sitter only) and runner (needs clang + LLVM tools)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from reqtrace_mcp.core.analysis import build_matrix, find_gaps, load_context
from reqtrace_mcp.core.annotations import scan
from reqtrace_mcp.core.annotations import test_nodeid as nodeid_of
from reqtrace_mcp.core.cfamily import gtest_base, scan_cfamily
from reqtrace_mcp.core.config import ReqtraceError, load_config
from reqtrace_mcp.core.impact import impact_of_change
from reqtrace_mcp.core.model import Status
from reqtrace_mcp.core.report import write_evidence
from reqtrace_mcp.core.runner import CoverageIndex, run_tests

from .conftest import git

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cdemo"

CPP_SOURCE = """\
#include <cstdint>
namespace demo {

// implements: REQ-001
uint32_t Sum(const uint8_t* data, size_t n) { return 0; }

// Overload for chars.
// implements: REQ-002
inline uint32_t Sum(const char* data, size_t n) { return 0; }

class Filter {
 public:
  // implements: REQ-003
  int Apply(int x) const { return x; }
  int Reset();
};

int Filter::Reset() { return 0; }  // implements: REQ-004

// implements: REQ-005
template <int N>
constexpr int RoundUp(int v) { return (v + N - 1) & ~(N - 1); }

}  // namespace demo

/* derived: table generator, no parent requirement */
static void BuildTable() {}
"""

HEADER_WITH_EXTERN_C = """\
#ifdef __cplusplus
extern "C" {
#endif
/* implements: REQ-010 */
static inline int c_api(int x) { return x; }
#ifdef __cplusplus
}
#endif
"""

GTEST_FILE = """\
#include "gtest/gtest.h"
// verifies: REQ-001
TEST(SumTest, Empty) { EXPECT_EQ(0u, demo::Sum(nullptr, 0)); }

// verifies: REQ-001, REQ-002
TYPED_TEST_P(SumTyped, Agrees) {}

TEST_F(FilterTest, Apply) {}  // verifies: REQ-003

static int helper() { return 1; }
"""


def by_qual(items):  # type: ignore[no-untyped-def]
    return {i.qualname: i for i in items}


@pytest.mark.verifies("RT-030")
def test_cpp_scanner_finds_functions_methods_overloads_and_templates() -> None:
    items = by_qual(scan_cfamily(CPP_SOURCE, "src/demo.cc", is_test=False))
    assert items["demo::Sum(const uint8_t*, size_t)"].implements == ["REQ-001"]
    assert items["demo::Sum(const char*, size_t)"].implements == ["REQ-002"]
    assert items["demo::Filter"].kind == "class"
    apply = items["demo::Filter.Apply"]
    assert (apply.kind, apply.implements) == ("method", ["REQ-003"])
    reset = items["demo::Filter.Reset"]  # out-of-line definition, trailing comment
    assert (reset.kind, reset.implements) == ("method", ["REQ-004"])
    rnd = items["demo::RoundUp"]  # annotation sits above the template line
    assert rnd.implements == ["REQ-005"] and rnd.start_line < rnd.def_line
    assert items["BuildTable"].derived == "table generator, no parent requirement"


@pytest.mark.verifies("RT-030")
def test_extern_c_header_parses_and_c_comments_work() -> None:
    items = by_qual(scan_cfamily(HEADER_WITH_EXTERN_C, "include/api.h", is_test=False))
    assert items["c_api"].implements == ["REQ-010"]


@pytest.mark.verifies("RT-030")
def test_gtest_macros_become_tests_and_helpers_do_not() -> None:
    items = scan_cfamily(GTEST_FILE, "tests/sum_unittest.cc", is_test=True)
    tests = {i.qualname: i.verifies for i in items if i.kind == "test"}
    assert tests == {
        "SumTest.Empty": ["REQ-001"],
        "SumTyped.Agrees": ["REQ-001", "REQ-002"],
        "FilterTest.Apply": ["REQ-003"],
    }
    item = next(i for i in items if i.qualname == "SumTest.Empty")
    assert nodeid_of(item) == "tests/sum_unittest.cc::SumTest.Empty"


@pytest.mark.verifies("RT-030")
def test_duplicate_signatures_in_if_branches_get_line_suffix() -> None:
    src = (
        "#if A\ninline bool Probe() { return true; }\n"
        "#else\ninline bool Probe() { return false; }\n#endif\n"
    )
    quals = sorted(i.qualname for i in scan_cfamily(src, "src/p.h", is_test=False))
    assert quals == ["Probe()@L2", "Probe()@L4"]


@pytest.mark.parametrize(
    ("runtime", "expected"),
    [
        ("Crc32CTest.Crc32c", ("Crc32CTest.Crc32c", "")),
        ("Portable/ExtendTest/0.HelloWorld", ("ExtendTest.HelloWorld", "Portable/0")),
        ("Inst/Suite.Name/3", ("Suite.Name", "Inst/3")),
        ("Typed/0.Name", ("Typed.Name", "0")),
    ],
)
@pytest.mark.verifies("RT-031")
def test_gtest_runtime_names_map_to_static_tests(runtime: str, expected: tuple[str, str]) -> None:
    assert gtest_base(runtime) == expected


@pytest.mark.verifies("RT-030")
def test_cpp_config_validation(tmp_path: Path) -> None:
    (tmp_path / ".reqtrace.yaml").write_text("language: cpp\n")
    with pytest.raises(ReqtraceError, match="tests"):
        load_config(tmp_path)
    (tmp_path / ".reqtrace.yaml").write_text(
        "language: cpp\nbuild: {commands: ['make all']}\ntests: [{binary: a}]\n"
    )
    with pytest.raises(ReqtraceError, match="argv list"):
        load_config(tmp_path)
    (tmp_path / ".reqtrace.yaml").write_text("language: cpp\ntests: [{binary: a, kind: ctest}]\n")
    with pytest.raises(ReqtraceError, match="gtest or exe"):
        load_config(tmp_path)
    (tmp_path / ".reqtrace.yaml").write_text("language: rust\n")
    with pytest.raises(ReqtraceError, match="language"):
        load_config(tmp_path)


# ------------------------------------------------------------- runner (clang) ---

needs_clang = pytest.mark.skipif(
    not (shutil.which("clang") and shutil.which("llvm-profdata") and shutil.which("llvm-cov")),
    reason="needs clang, llvm-profdata and llvm-cov",
)


@pytest.fixture
def crepo(tmp_path: Path) -> Path:
    dst = tmp_path / "cdemo"
    shutil.copytree(FIXTURE, dst, ignore=shutil.ignore_patterns(".reqtrace"))
    git(dst, "init", "-q", "-b", "main")
    git(dst, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    git(dst, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return dst


@needs_clang
@pytest.mark.verifies("RT-031", "RT-032")
def test_c_runner_statuses_failures_and_exe_tests(crepo: Path) -> None:
    cfg = load_config(crepo)
    sc = scan(cfg)
    assert sc.parse_errors == []
    run = run_tests(cfg)
    outcomes = {t.nodeid: t.outcome for t in run.tests}
    assert outcomes == {
        "tests/lim_unittest.c::LimTest.Clamp": "passed",
        "tests/lim_unittest.c::LimTest.Smoke": "passed",
        "tests/lim_unittest.c::LimTest.Percent": "failed",
        "tests/lim_unittest.c::WinTest.Bounds[Typed/0]": "passed",
        "tests/capi_check.c::main": "passed",
        "tests/unity_style.c::test_clamp_low": "passed",  # share the executable's result
        "tests/unity_style.c::test_clamp_high": "passed",
    }
    m = build_matrix(load_context(cfg))
    st = {t.requirement.id: t.status for t in m.requirements}
    assert st == {
        "LIM-001": Status.VERIFIED,  # gtest-style test, plain executables, Unity-style tests
        "LIM-002": Status.VERIFIED,  # typed-test instance mapped back to its definition
        "LIM-003": Status.WEAKLY_VERIFIED,  # test never calls scale()
        "LIM-004": Status.FAILING,
    }
    assert m.unrequired_code == ["src/lim.c::debug_dump"]
    gaps = find_gaps(load_context(cfg))
    failing = next(g for g in gaps if g.kind == "failing")
    assert "percent(1, 4) == 20" in failing.detail


@needs_clang
@pytest.mark.verifies("RT-032")
def test_c_runner_measures_branches_and_mcdc(crepo: Path) -> None:
    cfg = load_config(crepo)
    run_tests(cfg)
    ctx = load_context(cfg)
    m = build_matrix(ctx)
    win = next(t for t in m.requirements if t.requirement.id == "LIM-002")
    assert win.coverage is not None and win.coverage.mcdc_measured
    # in_window(0,0,45) and in_window(46,0,45) only show the second condition matters.
    assert (win.coverage.mcdc_conditions, win.coverage.mcdc_covered) == (2, 1)
    assert win.coverage.missing_mcdc == ["src/lim.c:12:10 condition 1/2"]
    assert {g.kind for g in find_gaps(ctx) if g.req_id == "LIM-002"} == {
        "uncovered_branch",
        "uncovered_condition",
    }
    clamp = next(t for t in m.requirements if t.requirement.id == "LIM-001")
    assert clamp.coverage is not None and clamp.coverage.branch_pct == 100.0
    assert isinstance(ctx.cov, CoverageIndex)
    assert ctx.cov.test_hits("tests/capi_check.c::main", "src/lim.c", 5, 7)
    assert not ctx.cov.test_hits("tests/lim_unittest.c::LimTest.Smoke", "src/lim.c", 16, 18)
    path, _, _ = write_evidence(ctx)
    assert "| MC/DC |" in path.read_text()


@needs_clang
@pytest.mark.verifies("RT-032")
def test_c_runner_runs_only_selected_tests(crepo: Path) -> None:
    cfg = load_config(crepo)
    run = run_tests(cfg, ["tests/lim_unittest.c::WinTest.Bounds"])
    assert [t.nodeid for t in run.tests] == ["tests/lim_unittest.c::WinTest.Bounds[Typed/0]"]


@needs_clang
@pytest.mark.verifies("RT-033")
def test_c_change_impact(crepo: Path) -> None:
    lim = crepo / "src" / "lim.c"
    lim.write_text(lim.read_text().replace("if (v > hi) return hi;", "if (v >= hi) return hi;"))
    test = crepo / "tests" / "lim_unittest.c"
    test.write_text(test.read_text().replace("== 20);", "== 25);"))
    res = impact_of_change(load_context(load_config(crepo)), "HEAD")
    assert set(res.affected_requirements) == {"LIM-001", "LIM-004"}
    # The edited test, plus every test linked to a requirement whose code changed.
    assert res.tests_to_rerun == [
        "tests/capi_check.c::main",
        "tests/lim_unittest.c::LimTest.Clamp",
        "tests/lim_unittest.c::LimTest.Percent",
        "tests/unity_style.c::test_clamp_high",
        "tests/unity_style.c::test_clamp_low",
    ]


@needs_clang
@pytest.mark.verifies("RT-032")
def test_uninstrumented_build_is_reported(crepo: Path) -> None:
    cfg_file = crepo / ".reqtrace.yaml"
    cfg_file.write_text(cfg_file.read_text().replace('"{coverage_flags}", ', ""))
    with pytest.raises(ReqtraceError, match="not instrumented"):
        run_tests(load_config(crepo))
