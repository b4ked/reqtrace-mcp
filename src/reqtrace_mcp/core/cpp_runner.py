"""Build and run C/C++ tests with clang source-based coverage, one test at a time.

Pipeline:
1. Run the configured build commands (argv lists from `.reqtrace.yaml`, no shell) with
   CC/CXX set to clang and coverage flags added to CFLAGS/CXXFLAGS/LDFLAGS:
   `-fprofile-instr-generate -fcoverage-mapping`, plus `-fcoverage-mcdc` on clang >= 18.
2. GoogleTest binaries: list the tests, then run each one alone (`--gtest_filter`) with its own
   `LLVM_PROFILE_FILE`, so every test gets its own coverage. Plain executables are one test.
3. `llvm-profdata merge` each test's profile and export its executed lines (lcov), then merge
   everything and export line, branch and MC/DC data (JSON) for the run.
4. Write `coverage_norm.json`, the same shape `CoverageIndex` reads for any language.

Security is the same as for Python: the processes started are the repo's own build and test
binaries named in its config, and clang/LLVM tools. No caller ever supplies a command.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .annotations import ScanResult, scan, test_nodeid
from .cfamily import gtest_base
from .config import Config, ReqtraceError, TestBinary, clean_path
from .model import RunSummary, TestOutcome

COVERAGE_FLAGS = ["-fprofile-instr-generate", "-fcoverage-mapping"]
MCDC_FLAG = "-fcoverage-mcdc"
SKIP_EXIT = 77  # automake/CTest convention for "skipped"


@dataclass
class Toolchain:
    cc: str
    cxx: str
    profdata: str
    cov: str
    major: int
    mcdc: bool


def _which(name: str) -> str | None:
    return shutil.which(name, path=os.pathsep.join(clean_path()))


def _clang_major(clang: str) -> int:
    try:
        out = subprocess.run([clang, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 0
    m = re.search(r"clang version (\d+)", out.stdout)
    return int(m.group(1)) if m else 0


def find_toolchain(cfg: Config) -> Toolchain:
    """clang/clang++ and the llvm-profdata/llvm-cov of the same major version (profile
    formats change between versions)."""
    cc = _which(cfg.cc) if cfg.cc else None
    if not cc:
        cc = _which("clang") or next(
            (p for v in range(25, 13, -1) if (p := _which(f"clang-{v}"))), None
        )
    if not cc:
        raise ReqtraceError(
            "C/C++ coverage needs clang (source-based coverage). Install clang and LLVM tools "
            "(e.g. apt install clang llvm), or set toolchain.cc/cxx in .reqtrace.yaml."
        )
    major = _clang_major(cc)
    cxx = _which(cfg.cxx) if cfg.cxx else None
    if not cxx:
        guess = cc.replace("clang", "clang++", 1) if "clang++" not in cc else cc
        cxx = guess if Path(guess).exists() else (_which("clang++") or guess)

    def tool(name: str) -> str:
        cands = [f"{name}-{major}", name] if major else [name]
        for c in cands:
            if p := _which(c):
                return p
        versioned = Path(f"/usr/lib/llvm-{major}/bin") / name
        if versioned.exists():
            return str(versioned)
        raise ReqtraceError(f"{name} (LLVM {major or '?'}) not found; install the llvm package")

    return Toolchain(
        cc, cxx, tool("llvm-profdata"), tool("llvm-cov"), major, cfg.mcdc and major >= 18
    )


def _build_env(cfg: Config, tc: Toolchain, base: dict[str, str]) -> dict[str, str]:
    env = dict(base)
    flags = " ".join([*COVERAGE_FLAGS, *([MCDC_FLAG] if tc.mcdc else [])])
    env["CC"], env["CXX"] = tc.cc, tc.cxx
    for var in ("CFLAGS", "CXXFLAGS"):
        env[var] = f"{env.get(var, '')} {flags}".strip()
    env["LDFLAGS"] = f"{env.get('LDFLAGS', '')} -fprofile-instr-generate".strip()
    env["REQTRACE_COVERAGE_FLAGS"] = flags
    return env


def build(cfg: Config, tc: Toolchain, rdir: Path, env: dict[str, str]) -> None:
    (cfg.root / cfg.build_dir).mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    try:
        flags = [*COVERAGE_FLAGS, *([MCDC_FLAG] if tc.mcdc else [])]
        for cmd in cfg.build_commands:
            argv: list[str] = []
            for a in cmd:  # {coverage_flags} expands to several arguments
                if a == "{coverage_flags}":
                    argv += flags
                else:
                    argv.append(cfg.expand(a).replace("{cc}", tc.cc).replace("{cxx}", tc.cxx))
            try:
                proc = subprocess.run(
                    argv,
                    cwd=cfg.root,
                    env=_build_env(cfg, tc, env),
                    capture_output=True,
                    text=True,
                    timeout=cfg.timeout_s,
                )
            except FileNotFoundError as exc:
                raise ReqtraceError(f"Build command not found: {argv[0]}") from exc
            except subprocess.TimeoutExpired as exc:
                raise ReqtraceError(
                    f"Build step timed out after {cfg.timeout_s}s: {' '.join(argv)}"
                ) from exc
            log.append(f"$ {' '.join(argv)}\n{proc.stdout}{proc.stderr}")
            if proc.returncode != 0:
                raise ReqtraceError(
                    f"Build step failed (exit {proc.returncode}): {' '.join(argv)}\n"
                    + (proc.stdout + proc.stderr).strip()[-1500:]
                )
    finally:
        (rdir / "build.log").write_text("\n".join(log), encoding="utf-8")


def list_gtests(binary: str, env: dict[str, str], cwd: Path) -> list[str]:
    proc = subprocess.run(
        [binary, "--gtest_list_tests"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise ReqtraceError(f"{binary} --gtest_list_tests failed: {proc.stderr.strip()[-500:]}")
    names: list[str] = []
    suite = ""
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        body = line.split("#", 1)[0].strip()
        if not line.startswith(" "):
            suite = body
        elif suite:
            names.append(suite + body)
    return names


def _gtest_outcome(report: Path, output: str) -> tuple[str, str]:
    if not report.exists():
        return "error", "E crashed or exited before writing a result\n" + output[-1500:]
    data = json.loads(report.read_text())
    for suite in data.get("testsuites", []):
        for case in suite.get("testsuite", []):
            fails = case.get("failures") or []
            if fails:
                msg = "\n".join(
                    "E " + ln for f in fails for ln in str(f.get("failure", "")).splitlines()[:6]
                )
                return "failed", msg
            if case.get("result") == "SKIPPED" or case.get("status") == "NOTRUN":
                return "skipped", ""
            return "passed", ""
    return "error", "E no test matched the filter\n" + output[-500:]


def _rel(cfg: Config, name: str) -> str | None:
    try:
        return Path(name).resolve().relative_to(cfg.root).as_posix()
    except (ValueError, OSError):
        return None


def _in_dirs(relp: str, dirs: list[str]) -> bool:
    for d in dirs:
        d = d.strip("/").removeprefix("./")
        if d in ("", ".") or relp == d or relp.startswith(d + "/"):
            return True
    return False


def _lcov_lines(text: str, cfg: Config) -> dict[str, dict[int, int]]:
    """lcov `SF:`/`DA:` records -> {relpath: {line: max count}} for files in source dirs."""
    out: dict[str, dict[int, int]] = {}
    cur: dict[int, int] | None = None
    for line in text.splitlines():
        if line.startswith("SF:"):
            relp = _rel(cfg, line[3:])
            cur = (
                out.setdefault(relp, {})
                if relp and _in_dirs(relp, cfg.source_dirs) and ".reqtrace" not in relp.split("/")
                else None
            )
        elif line.startswith("DA:") and cur is not None:
            ln, cnt = line[3:].split(",")[:2]
            cur[int(ln)] = max(cur.get(int(ln), 0), int(float(cnt)))
        elif line == "end_of_record":
            cur = None
    return out


def _merge(tc: Toolchain, raws: list[Path], out: Path) -> bool:
    raws = [r for r in raws if r.exists()]
    if not raws:
        return False
    subprocess.run(
        [tc.profdata, "merge", "-sparse", *map(str, raws), "-o", str(out)],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return True


def _export(tc: Toolchain, profdata: Path, binaries: list[str], fmt: str) -> str:
    argv = [
        tc.cov,
        "export",
        f"-format={fmt}",
        f"-instr-profile={profdata}",
        binaries[0],
        *[f"-object={b}" for b in binaries[1:]],
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise ReqtraceError(f"llvm-cov export failed: {proc.stderr.strip()[-500:]}")
    return proc.stdout


def _branches_and_mcdc(cfg: Config, export: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per file: branch outcomes and MC/DC conditions from `llvm-cov export` JSON.

    branches: [line, col, end_line, end_col, true_count, false_count, ...] -> two outcomes.
    mcdc_records: [line, col, end_line, end_col, ..., [covered per condition]].
    Template instantiations repeat regions; they are merged by position.
    """
    files: dict[str, dict[str, Any]] = {}
    for data in export.get("data", []):
        for f in data.get("files", []):
            relp = _rel(cfg, f.get("filename", ""))
            if not relp or not _in_dirs(relp, cfg.source_dirs):
                continue
            entry = files.setdefault(relp, {"branches": {}, "mcdc": {}})
            for b in f.get("branches", []):
                key = (b[0], b[1])
                t, fl = entry["branches"].get(key, (0, 0))
                entry["branches"][key] = (t + int(b[4]), fl + int(b[5]))
            for r in f.get("mcdc_records", []):
                conds = next((x for x in r if isinstance(x, list)), [])
                key = (r[0], r[1])
                prev = entry["mcdc"].get(key, [False] * len(conds))
                entry["mcdc"][key] = (
                    [a or bool(b) for a, b in zip(prev, conds, strict=True)]
                    if len(prev) == len(conds)
                    else [bool(c) for c in conds]
                )
    out: dict[str, dict[str, Any]] = {}
    for relp, e in files.items():
        branches = []
        for (ln, col), (t, fl) in sorted(e["branches"].items()):
            branches.append([ln, f"{ln}:{col} true", t > 0])
            branches.append([ln, f"{ln}:{col} false", fl > 0])
        mcdc = []
        for (ln, col), conds in sorted(e["mcdc"].items()):
            n = len(conds)
            mcdc += [[ln, f"{ln}:{col} condition {k + 1}/{n}", c] for k, c in enumerate(conds)]
        out[relp] = {"branches": branches, "mcdc": mcdc}
    return out


def _static_tests(sc: ScanResult) -> tuple[dict[str, list[Any]], dict[str, list[Any]]]:
    by_qual: dict[str, list[Any]] = {}
    by_path: dict[str, list[Any]] = {}
    for i in sc.test_items:
        by_qual.setdefault(i.qualname, []).append(i)
        by_path.setdefault(i.path, []).append(i)
    return by_qual, by_path


def run_cpp_tests(
    cfg: Config, rdir: Path, env: dict[str, str], node_ids: list[str] | None
) -> tuple[list[TestOutcome], list[str], bool, str]:
    """Build, run and measure. Returns (outcomes, command summary, timed_out, output tail)."""
    tc = find_toolchain(cfg)
    build(cfg, tc, rdir, env)
    sc = scan(cfg)
    by_qual, by_path = _static_tests(sc)
    wanted = set(node_ids or [])
    prof = rdir / "profiles"
    prof.mkdir(exist_ok=True)
    outcomes: list[TestOutcome] = []
    per_test_raw: list[tuple[str, str, Path]] = []  # (base nodeid, binary, profraw)
    binaries: list[str] = []
    deadline = time.monotonic() + cfg.timeout_s
    timed_out = False
    log: list[str] = []
    counter = 0

    def run_one(argv: list[str], raw: Path) -> tuple[int | None, str, float]:
        nonlocal timed_out
        left = deadline - time.monotonic()
        if left <= 0:
            timed_out = True
            return None, "", 0.0
        e = dict(env, LLVM_PROFILE_FILE=str(raw))
        t0 = time.monotonic()
        try:
            p = subprocess.run(
                argv, cwd=cfg.root, env=e, capture_output=True, text=True, timeout=left
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            return None, "timed out", time.monotonic() - t0
        return p.returncode, p.stdout + p.stderr, time.monotonic() - t0

    for tb in cfg.tests:
        binary = cfg.expand(tb.binary)
        if not Path(binary).is_absolute():
            binary = str(cfg.root / binary)
        if not Path(binary).exists():
            raise ReqtraceError(f"Test binary {tb.binary} was not built ({binary})")
        binaries.append(binary)
        if tb.kind == "gtest":
            listing_env = dict(env, LLVM_PROFILE_FILE=str(prof / "listing-%p.profraw"))
            for full in list_gtests(binary, listing_env, cfg.root):
                base, inst = gtest_base(full)
                static = by_qual.get(base, [])
                item = static[0] if static else None
                node = test_nodeid(item) if item else f"{Path(binary).name}::{base}"
                if wanted and node not in wanted:
                    continue
                counter += 1
                raw, report = prof / f"t{counter}.profraw", prof / f"t{counter}.json"
                code, out, dur = run_one(
                    [binary, f"--gtest_filter={full}", f"--gtest_output=json:{report}", *tb.args],
                    raw,
                )
                if code is None and timed_out:
                    break
                outcome, msg = _gtest_outcome(report, out)
                log.append(f"[{outcome}] {full}")
                outcomes.append(
                    TestOutcome(
                        nodeid=f"{node}[{inst}]" if inst else node,
                        outcome=outcome,  # type: ignore[arg-type]
                        duration_s=round(dur, 3),
                        verifies=list(item.verifies) if item else [],
                        message=msg,
                    )
                )
                per_test_raw.append((node, binary, raw))
        else:
            # A plain executable is one result. Every test item in its source file (its
            # annotated `main`, or Unity/CMocka-style test_* functions) shares that result.
            src_items = by_path.get(tb.source or "", [])
            nodes = [(test_nodeid(i), list(i.verifies)) for i in src_items] or [
                (f"{tb.source}::main" if tb.source else f"{Path(binary).name}::main", [])
            ]
            if wanted and not any(n in wanted for n, _ in nodes):
                continue
            counter += 1
            raw = prof / f"t{counter}.profraw"
            code, out, dur = run_one([binary, *tb.args], raw)
            if code is None and timed_out:
                break
            outcome = "passed" if code == 0 else "skipped" if code == SKIP_EXIT else "failed"
            msg = (
                ""
                if outcome != "failed"
                else (f"E exit code {code}\n" + "\n".join(out.strip().splitlines()[-8:]))
            )
            log.append(f"[{outcome}] {Path(binary).name}")
            for node, verifies in nodes:
                outcomes.append(
                    TestOutcome(
                        nodeid=node,
                        outcome=outcome,  # type: ignore[arg-type]
                        duration_s=round(dur, 3),
                        verifies=verifies,
                        message=msg,
                    )
                )
                per_test_raw.append((node, binary, raw))
        if timed_out:
            break

    _write_coverage(cfg, tc, rdir, per_test_raw, binaries)
    for p in prof.glob("listing-*.profraw"):
        p.unlink()
    command = [
        *(Path(b).name for b in binaries),
        "(one process per test, clang coverage" + (" + MC/DC)" if tc.mcdc else ")"),
    ]
    return outcomes, command, timed_out, "\n".join(log)


def _write_coverage(
    cfg: Config,
    tc: Toolchain,
    rdir: Path,
    per_test: list[tuple[str, str, Path]],
    binaries: list[str],
) -> None:
    present = [(n, b, r) for (n, b, r) in per_test if r.exists()]
    if per_test and not present:
        raise ReqtraceError(
            "Tests ran but wrote no coverage profiles: the build was probably not instrumented. "
            "Make sure the build honours CC, CXX, CFLAGS, CXXFLAGS and LDFLAGS (CMake does on a "
            f"fresh build dir), or add $REQTRACE_COVERAGE_FLAGS yourself. Build log: "
            f"{rdir / 'build.log'}"
        )
    tests: dict[str, dict[str, set[int]]] = {}
    exported: dict[Path, dict[str, dict[int, int]]] = {}
    for node, binary, raw in present:
        if raw not in exported:  # an exe's tests share one profile
            pd = raw.with_suffix(".profdata")
            if not _merge(tc, [raw], pd):
                continue
            exported[raw] = _lcov_lines(_export(tc, pd, [binary], "lcov"), cfg)
            pd.unlink()
        for relp, lines in exported[raw].items():
            hit = {ln for ln, c in lines.items() if c > 0}
            if hit:
                tests.setdefault(node, {}).setdefault(relp, set()).update(hit)
    files: dict[str, dict[str, Any]] = {}
    merged = rdir / "merged.profdata"
    used = sorted({b for (_n, b, _r) in present})
    if used and _merge(tc, sorted({r for (_n, _b, r) in present}), merged):
        merged_lines = _lcov_lines(_export(tc, merged, used, "lcov"), cfg)
        extra = _branches_and_mcdc(cfg, json.loads(_export(tc, merged, used, "text")))
        for relp, da in merged_lines.items():
            files[relp] = {
                "executed_lines": sorted(ln for ln, c in da.items() if c > 0),
                "missing_lines": sorted(ln for ln, c in da.items() if c == 0),
                **extra.get(relp, {"branches": [], "mcdc": []}),
            }
    norm = {
        "tool": f"llvm-cov {tc.major}",
        "mcdc": tc.mcdc,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
        "tests": {n: {p: sorted(s) for p, s in f.items()} for n, f in tests.items()},
    }
    (rdir / "coverage_norm.json").write_text(json.dumps(norm), encoding="utf-8")
    for _n, _b, raw in present:  # merged.profdata keeps everything `llvm-cov show` needs
        raw.unlink(missing_ok=True)


def summary_for(
    run_id: str,
    started: str,
    duration: float,
    outcomes: list[TestOutcome],
    command: list[str],
    timed_out: bool,
    tail: str,
) -> RunSummary:
    failed = any(t.outcome in ("failed", "error") for t in outcomes)
    return RunSummary(
        run_id=run_id,
        started_at=started,
        duration_s=round(duration, 2),
        exit_code=1 if failed or timed_out else 0,
        command=command,
        tests=outcomes,
        timed_out=timed_out,
        stderr_tail=tail[-800:],
    )


__all__ = ["TestBinary", "find_toolchain", "run_cpp_tests", "summary_for"]
