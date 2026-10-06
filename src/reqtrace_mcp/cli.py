"""`reqtrace` command line: the same functions the MCP server exposes, for humans and CI."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any

from .core import requirements as reqmod
from .core.analysis import build_matrix, find_gaps, load_context
from .core.config import ReqtraceError, find_root, load_config
from .core.impact import impact_of_change
from .core.model import CoverageFigures
from .core.report import write_evidence
from .core.runner import run_tests
from .core.state import flag_issue, record_review, set_suggestion_status


def _print(obj: Any, as_json: bool, text: str) -> None:
    if as_json:
        print(json.dumps(obj, indent=1, default=str))
    else:
        print(text)


def gate_counts(gaps: list[Any]) -> Counter[str]:
    return Counter(g.kind for g in gaps)


def _cov_text(cov: CoverageFigures | None) -> str:
    if cov is None:
        return ""
    out = f" stmt={_pct(cov.statement_pct)} branch={_pct(cov.branch_pct)}"
    return out + (f" mcdc={_pct(cov.mcdc_pct)}" if cov.mcdc_measured else "")


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0f}%"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reqtrace", description=__doc__)
    p.add_argument("--root", help="Repository root (default: $CLAUDE_PROJECT_DIR or cwd)")
    p.add_argument("--json", action="store_true", help="Machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("matrix", help="Show the trace matrix")
    sub.add_parser("gaps", help="List gaps")
    sub.add_parser("lint", help="Lint requirements")
    v = sub.add_parser("verify", help="Run tests under coverage and update status")
    v.add_argument("req_ids", nargs="*")
    i = sub.add_parser("impact", help="Requirements affected by a git diff")
    i.add_argument("--base", default="HEAD")
    i.add_argument("--committed-only", action="store_true")
    sub.add_parser("report", help="Write the evidence pack to .reqtrace/evidence/")
    r = sub.add_parser("review", help="Record a human review (sign-off)")
    r.add_argument("req_ids", nargs="+")
    grp = r.add_mutually_exclusive_group(required=True)
    grp.add_argument("--approve", action="store_true")
    grp.add_argument("--reject", action="store_true")
    r.add_argument("--reviewer", required=True)
    r.add_argument("--rationale", required=True)
    f = sub.add_parser("flag", help="Flag a requirement issue")
    f.add_argument("req_id")
    f.add_argument(
        "--kind",
        default="ambiguous",
        choices=["ambiguous", "conflict", "untestable", "incomplete", "other"],
    )
    f.add_argument("--description", required=True)
    lk = sub.add_parser("links", help="Accept or reject agent-suggested links")
    lk.add_argument("action", choices=["accept", "reject"])
    lk.add_argument("suggestion_id")
    gt = sub.add_parser("gate", help="Exit 1 if gaps exceed thresholds in .reqtrace.yaml")
    gt.add_argument("--verify", action="store_true", help="Run the tests first")
    s = sub.add_parser("serve", help="Run the MCP server on stdio")
    s.add_argument("--transport", default="stdio", choices=["stdio"])
    args = p.parse_args(argv)

    try:
        if args.cmd == "serve":
            from .server import main as serve_main

            serve_main(["--root", args.root] if args.root else [])
            return 0
        cfg = load_config(find_root(args.root))
        if args.cmd == "lint":
            findings = reqmod.lint(reqmod.load_requirements(cfg))
            _print(
                [x.model_dump() for x in findings],
                args.json,
                "\n".join(f"{x.severity:7} {x.req_id or '-':8} {x.message}" for x in findings)
                or "No findings.",
            )
            return 0
        if args.cmd == "verify":
            ctx = load_context(cfg)
            nodes = None
            if args.req_ids:
                from .core.analysis import verifying_tests

                nodes = sorted({n for rid in args.req_ids for n in verifying_tests(ctx, rid)})
            summary = run_tests(cfg, nodes)
            c = Counter(t.outcome for t in summary.tests)
            _print(
                summary.model_dump(),
                args.json,
                f"run {summary.run_id}: {dict(c)} in {summary.duration_s}s"
                + (" TIMED OUT" if summary.timed_out else ""),
            )
            return 0 if not c.get("failed") and not c.get("error") else 1
        ctx = load_context(cfg)
        if args.cmd == "matrix":
            m = build_matrix(ctx)
            text = (
                "\n".join(
                    f"{t.requirement.id:10} {t.status.value:16} impl={len(t.implemented_by)} "
                    f"tests={len(t.verified_by)} exercising={len(t.tests_exercising_code)}"
                    + _cov_text(t.coverage)
                    for t in m.requirements
                )
                + f"\nunrequired code: {len(m.unrequired_code)}"
            )
            _print(m.model_dump(), args.json, text)
        elif args.cmd == "gaps":
            gaps = find_gaps(ctx)
            _print(
                [g.model_dump() for g in gaps],
                args.json,
                "\n".join(f"{g.kind:22} {g.req_id or '':9} {g.detail}" for g in gaps) or "No gaps.",
            )
        elif args.cmd == "impact":
            res = impact_of_change(ctx, args.base, not args.committed_only)
            _print(res.model_dump(), args.json, res.model_dump_json(indent=1))
        elif args.cmd == "report":
            path, m, gaps = write_evidence(ctx)
            _print(
                {"path": str(path), "counts": m.counts(), "gaps": len(gaps)},
                args.json,
                f"Wrote {path}",
            )
        elif args.cmd == "review":
            reqs = {r.id: r for r in ctx.reqs}
            for rid in args.req_ids:
                if rid not in reqs:
                    raise ReqtraceError(f"Unknown requirement {rid}")
                rv = record_review(
                    cfg,
                    reqs[rid],
                    ctx.scan,
                    "approved" if args.approve else "rejected",
                    args.reviewer,
                    args.rationale,
                    ctx.extra_links,
                )
                print(f"{rv.req_id}: {rv.decision} by {rv.reviewer} (hash {rv.content_hash})")
        elif args.cmd == "flag":
            iss = flag_issue(cfg, args.req_id, args.kind, args.description, raised_by="human")
            print(f"{iss.id} raised on {iss.req_id}")
        elif args.cmd == "links":
            sg = set_suggestion_status(
                cfg, args.suggestion_id, "accepted" if args.action == "accept" else "rejected"
            )
            print(f"{sg.id}: {sg.status}")
        elif args.cmd == "gate":
            if args.verify:
                run_tests(cfg)
                ctx = load_context(cfg)
            return _gate(cfg, ctx, args.json)
        return 0
    except ReqtraceError as exc:
        print(f"reqtrace: {exc}", file=sys.stderr)
        return 2


def _gate(cfg: Any, ctx: Any, as_json: bool) -> int:
    gaps = find_gaps(ctx)
    c = gate_counts(gaps)
    limits = {
        "unimplemented": cfg.gate.max_unimplemented,
        "untested": cfg.gate.max_untested,
        "failing": cfg.gate.max_failing,
        "weakly_verified": cfg.gate.max_weakly_verified,
        "unrequired_code": cfg.gate.max_unrequired,
    }
    breaches = {k: c.get(k, 0) for k, lim in limits.items() if c.get(k, 0) > lim}
    if as_json:
        print(json.dumps({"pass": not breaches, "breaches": breaches, "counts": dict(c)}))
    elif breaches:
        print(
            "reqtrace gate FAILED: "
            + ", ".join(f"{k}={v} (max {limits[k]})" for k, v in breaches.items())
        )
        for g in gaps:
            if g.kind in breaches:
                print(f"  - {g.kind}: {g.req_id or g.location}: {g.next_action}")
    else:
        print("reqtrace gate passed")
    return 1 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
