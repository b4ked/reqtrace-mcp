"""Aggregate graded runs into summary.json, RESULTS.md and a chart.

Everything is reported, including metrics where reqtrace does worse. Only runs with status
"ok" are aggregated; infrastructure errors are counted and listed, never silently dropped.
"""

from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

# (key, label, which task types, higher_is_better, is_fraction)
METRICS: list[tuple[str, str, set[str], bool, bool]] = [
    ("task_success", "Task success (pass@1)", {"implement", "change", "review", "ambiguity"},
     True, True),
    ("hidden_pass_rate", "Hidden acceptance tests passed", {"implement", "change", "ambiguity"},
     True, True),
    ("verification_strength", "Verification strength (traced mutant kills)",
     {"implement", "change", "ambiguity"}, True, True),
    ("detection_any_test", "Mutants killed by any agent test", {"implement", "change",
                                                                "ambiguity"}, True, True),
    ("req_coverage", "Requirements VERIFIED (reqtrace's own check)",
     {"implement", "change", "ambiguity"}, True, True),
    ("link_precision", "Test→requirement link precision", {"implement", "change", "ambiguity"},
     True, True),
    ("impl_precision", "Code→requirement link precision", {"implement", "change", "ambiguity"},
     True, True),
    ("impl_recall", "Code→requirement link recall", {"implement", "change", "ambiguity"},
     True, True),
    ("unrequired_code", "Unrequired code items", {"implement", "change", "ambiguity"},
     False, False),
    ("tests_failing_on_reference", "Agent tests that fail on correct code",
     {"implement", "change", "ambiguity"}, False, False),
    ("detection_rate", "Seeded defects found", {"review"}, True, True),
    ("false_positives", "False-positive defect findings", {"review"}, False, False),
    ("ambiguity_flagged", "Requirement conflict flagged", {"ambiguity"}, True, True),
    ("edited_source", "Edited files during review (should be 0)", {"review"}, False, True),
]
COST: list[tuple[str, str]] = [
    ("cost_usd_list", "Cost per run, list-price USD"), ("num_turns", "Turns"),
    ("wall_s", "Wall-clock seconds"), ("tool_calls", "Tool calls"),
    ("reqtrace_calls", "reqtrace tool calls"),
]
COLORS = {"baseline": "#2a78d6", "reqtrace": "#eb6834"}  # validated pair (dataviz skill)
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    return None


def load_runs(results: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(results.glob("runs/*/*/r*/run.json"))]


def per_task(runs: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """(task, condition) -> metric -> list of per-run values."""
    out: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: defaultdict(list))
    for r in runs:
        if r.get("status") != "ok":
            continue
        cell = out[(r["task"], r["condition"])]
        cell["_type"] = r["type"]
        g = r.get("grade", {})
        for key, *_ in METRICS:
            v = _num(g.get(key))
            if v is not None:
                cell[key].append(v)
        for key, _ in COST:
            v = _num(r.get(key))
            if v is not None:
                cell[key].append(v)
        cell["_runs"].append(r["run"])
    return out


def bootstrap_ci(diffs: list[float], n: int = 10000, seed: int = 7) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def summarise(results: Path) -> dict[str, Any]:
    runs = load_runs(results)
    cells = per_task(runs)
    manifest = json.loads((results / "manifest.json").read_text())
    conds = manifest["conditions"]
    tasks = sorted({t for t, _ in cells})
    summary: dict[str, Any] = {
        "manifest": manifest, "runs_total": len(runs),
        "runs_ok": sum(r.get("status") == "ok" for r in runs),
        "runs_not_ok": [f"{r['task']}/{r['condition']}/r{r['run']}: {r.get('status')}"
                        for r in runs if r.get("status") != "ok"],
        "metrics": {}, "cost": {}, "per_task": {}, "paired": {},
    }
    for key, label, types, better, _frac in METRICS:
        row: dict[str, Any] = {"label": label, "higher_is_better": better}
        task_means: dict[str, dict[str, float]] = {}
        for c in conds:
            vals = []
            for t in tasks:
                cell = cells.get((t, c))
                if cell and cell["_type"] in types and cell[key]:
                    m = statistics.fmean(cell[key])
                    vals.append(m)
                    task_means.setdefault(t, {})[c] = m
            row[c] = statistics.fmean(vals) if vals else None
            row[f"{c}_n_tasks"] = len(vals)
        if len(conds) == 2:
            a, b = conds
            diffs = [m[b] - m[a] for m in task_means.values() if a in m and b in m]
            if diffs:
                row["diff"] = statistics.fmean(diffs)
                row["diff_ci95"] = bootstrap_ci(diffs) if len(diffs) >= 4 else None
                row["n_paired_tasks"] = len(diffs)
        summary["metrics"][key] = row
    # pass^k: tasks where every run succeeded
    for c in conds:
        ok = [all(v == 1.0 for v in cells[(t, c)]["task_success"]) for t in tasks
              if (t, c) in cells and cells[(t, c)]["task_success"]]
        summary["metrics"].setdefault("pass_all_k", {"label": "All runs succeed (pass^k)",
                                                      "higher_is_better": True})
        summary["metrics"]["pass_all_k"][c] = statistics.fmean(ok) if ok else None
    for key, label in COST:
        summary["cost"][key] = {"label": label}
        for c in conds:
            vals = [v for t in tasks if (t, c) in cells for v in cells[(t, c)][key]]
            summary["cost"][key][c] = statistics.fmean(vals) if vals else None
            summary["cost"][key][f"{c}_total"] = sum(vals) if vals else None
    for t in tasks:
        summary["per_task"][t] = {}
        for c in conds:
            cell = cells.get((t, c))
            if not cell:
                continue
            summary["per_task"][t][c] = {
                k: (statistics.fmean(cell[k]) if cell[k] else None,
                    statistics.pstdev(cell[k]) if len(cell[k]) > 1 else None)
                for k in ["task_success", "verification_strength", "hidden_pass_rate",
                          "link_precision", "detection_rate", "false_positives",
                          "cost_usd_list", "num_turns"]
            }
            summary["per_task"][t][c]["runs"] = len(cell["_runs"])
            summary["per_task"][t]["type"] = cell["_type"]
    return summary


def _fmt(v: Any, frac: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v:.2f}" if frac else f"{v:.2f}"


def chart(summary: dict[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    conds = summary["manifest"]["conditions"]
    keys = ["task_success", "hidden_pass_rate", "verification_strength", "req_coverage",
            "link_precision", "detection_rate"]
    rows = [(summary["metrics"][k]["label"], [summary["metrics"][k].get(c) for c in conds])
            for k in keys if any(summary["metrics"][k].get(c) is not None for c in conds)]
    fig, ax = plt.subplots(figsize=(8, 0.55 * len(rows) + 1.6), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    h = 0.3
    n = len(conds)
    for i, (_label, vals) in enumerate(reversed(rows)):
        for j, (c, v) in enumerate(zip(conds, vals, strict=True)):
            if v is None:
                continue
            # first condition on top, matching the legend order
            y = i + ((n - 1) / 2 - j) * (h + 0.04)
            ax.barh(y, v, height=h, color=COLORS.get(c, INK2), edgecolor=SURFACE, linewidth=2)
            ax.text(v + 0.012, y, f"{v:.2f}", va="center", ha="left", fontsize=8, color=INK2)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in reversed(rows)], fontsize=9, color=INK)
    ax.set_xlim(0, 1.1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.tick_params(axis="x", colors=INK2, labelsize=8)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_visible(False)
    m = summary["manifest"]
    fig.text(0.01, 0.985, "Claude Code with vs without reqtrace", fontsize=11, color=INK,
             ha="left", va="top", weight="bold")
    fig.text(0.01, 0.94, f"Mean over tasks · {len(m['tasks'])} tasks × {m['runs']} run(s) · "
             f"{m['model']}", fontsize=8.5, color=INK2, ha="left", va="top")
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS.get(c, INK2)) for c in conds]
    fig.legend(handles, conds, loc="upper right", bbox_to_anchor=(0.99, 0.99), ncol=len(conds),
               frameon=False, fontsize=9, labelcolor=INK, handlelength=1.2)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(path, facecolor=SURFACE)
    fig.savefig(path.with_suffix(".svg"), facecolor=SURFACE)
    plt.close(fig)


def markdown(summary: dict[str, Any]) -> str:
    m = summary["manifest"]
    conds = m["conditions"]
    v = m["versions"]
    lines = [
        f"### Run: {m['started']} — {len(m['tasks'])} tasks × {len(conds)} conditions × "
        f"{m['runs']} run(s)",
        "",
        f"Model `{m['model']}` · Claude Code {v.get('claude_code')} · MCP SDK {v.get('mcp_sdk')}"
        f" · reqtrace `{v.get('reqtrace')}` · {summary['runs_ok']}/{summary['runs_total']} runs "
        "graded" + (f" (not graded: {', '.join(summary['runs_not_ok'])})"
                    if summary["runs_not_ok"] else ""),
        "",
        "Means are over tasks (each task's mean over its runs). Δ = reqtrace − baseline, paired "
        "by task; 95% CI by bootstrap over tasks when ≥ 4 tasks contribute.",
        "",
        f"| Metric | {' | '.join(conds)} | Δ | 95% CI | tasks |",
        f"|---|{'---|' * len(conds)}---|---|---|",
    ]
    for row in summary["metrics"].values():
        ci = row.get("diff_ci95")
        arrow = "" if row.get("higher_is_better", True) else " (lower is better)"
        lines.append(
            f"| {row['label']}{arrow} | " + " | ".join(_fmt(row.get(c)) for c in conds)
            + f" | {_fmt(row.get('diff'))} | "
            + (f"[{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "—")
            + f" | {row.get('n_paired_tasks', row.get(f'{conds[0]}_n_tasks', '—'))} |")
    lines += ["", f"| Cost (mean per run) | {' | '.join(conds)} |", f"|---|{'---|' * len(conds)}"]
    for _key, row in summary["cost"].items():
        lines.append(f"| {row['label']} | " + " | ".join(_fmt(row.get(c)) for c in conds) + " |")
    lines += ["", "**Per task** (mean over runs; sd in brackets when > 1 run)", "",
              "| Task | Type | " + " | ".join(f"{c} success" for c in conds) + " | "
              + " | ".join(f"{c} strength / defects" for c in conds) + " | "
              + " | ".join(f"{c} $" for c in conds) + " |",
              "|---|---|" + "---|" * (3 * len(conds))]
    for t, d in summary["per_task"].items():
        def cell(c: str, k: str, d: dict[str, Any] = d) -> str:
            mean, sd = d.get(c, {}).get(k, (None, None))
            return "—" if mean is None else (f"{mean:.2f}" + (f" ({sd:.2f})" if sd else ""))
        lines.append(
            f"| {t} | {d.get('type')} | " + " | ".join(cell(c, "task_success") for c in conds)
            + " | " + " | ".join(cell(c, "detection_rate") if d.get("type") == "review"
                                 else cell(c, "verification_strength") for c in conds)
            + " | " + " | ".join(cell(c, "cost_usd_list") for c in conds) + " |")
    return "\n".join(lines) + "\n"


def write_report(results: Path) -> None:
    summary = summarise(results)
    (results / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    (results / "summary.md").write_text(markdown(summary))
    try:
        chart(summary, results / "summary.png")
    except ImportError:
        print("matplotlib not installed: skipping chart (pip install '.[eval]')")
    print((results / "summary.md").read_text())
