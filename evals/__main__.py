"""python -m evals {check,run,report}"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .grade import self_check
from .runner import CONDITIONS, check_workdir, prewarm, run_one, versions
from .tasks import all_task_ids, load_task

DEFAULT_MODEL = "claude-sonnet-5-5"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="Validate every task (reference, mutants, hidden tests)")
    r = sub.add_parser("run", help="Run agents and grade them")
    r.add_argument("--tasks", default="all", help="Comma-separated task ids or prefixes")
    r.add_argument("--conditions", default="baseline,reqtrace")
    r.add_argument("--runs", type=int, default=3)
    r.add_argument("--model", default=DEFAULT_MODEL)
    r.add_argument("--out", default=None, help="Results dir (default evals/results/<time>)")
    r.add_argument("--workdir", default=None,
                   help="Agent workspaces, outside this repo (default ~/.cache/reqtrace-eval)")
    r.add_argument("-j", "--jobs", type=int, default=1)
    r.add_argument("--timeout", type=int, default=1500)
    r.add_argument("--force", action="store_true", help="Re-run even completed runs")
    rg = sub.add_parser("regrade", help="Re-grade existing workspaces with the current graders")
    rg.add_argument("results")
    rp = sub.add_parser("report", help="Aggregate results into RESULTS.md and charts")
    rp.add_argument("results")
    args = p.parse_args(argv)

    if args.cmd == "check":
        bad = 0
        for tid in all_task_ids():
            probs = self_check(load_task(tid))
            print(f"{tid:34} {probs or 'OK'}")
            bad += bool(probs)
        return 1 if bad else 0

    if args.cmd == "regrade":
        from .runner import regrade_all

        n = regrade_all(Path(args.results))
        print(f"Re-graded {n} runs")
        return 0

    if args.cmd == "report":
        from .report import write_report

        write_report(Path(args.results))
        return 0

    ids = all_task_ids()
    if args.tasks != "all":
        wanted = [w.strip() for w in args.tasks.split(",")]
        ids = [i for i in ids if any(i == w or i.startswith(w) for w in wanted)]
    conds = [c.strip() for c in args.conditions.split(",")]
    for c in conds:
        if c not in CONDITIONS:
            p.error(f"unknown condition {c}")
    out = Path(args.out or f"evals/results/{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    out.mkdir(parents=True, exist_ok=True)
    work = Path(args.workdir or Path.home() / ".cache" / "reqtrace-eval" / out.name)
    check_workdir(work)
    manifest = {"started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "model": args.model, "tasks": ids, "conditions": conds, "runs": args.runs,
                "versions": versions(), "allowed_tools": CONDITIONS}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    if "reqtrace" in conds:
        prewarm()
    # Interleave conditions so time-of-day / rate-limit effects hit both arms equally.
    jobs = [(tid, c, k) for k in range(1, args.runs + 1) for tid in ids for c in conds]
    tasks = {tid: load_task(tid) for tid in ids}

    def go(job: tuple[str, str, int]) -> None:
        tid, c, k = job
        rec = run_one(tasks[tid], c, k, out, work, args.model, args.timeout, args.force)
        g = rec.get("grade", {})
        print(f"{tid:32} {c:9} r{k} {rec['status']:12} success={g.get('task_success')} "
              f"turns={rec.get('num_turns')} ${rec.get('cost_usd_list') or 0:.2f} "
              f"{rec.get('wall_s')}s", flush=True)

    if args.jobs > 1:
        with ThreadPoolExecutor(args.jobs) as ex:
            list(ex.map(go, jobs))
    else:
        for j in jobs:
            go(j)
    print(f"Results in {out}. Next: python -m evals report {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
