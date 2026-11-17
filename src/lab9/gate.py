"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems = []

    # 1. Any metric value in pr["metrics"] that is NaN or inf
    for k, v in pr.get("metrics", {}).items():
        if isinstance(v, (int, float)):
            if math.isnan(v) or math.isinf(v):
                problems.append(f"metric {k} is NaN or inf ({v})")

    # 2. len(pr["rows"]) != manifest items x len(manifest seeds)
    manifest = pr.get("manifest", {})
    expected_rows = manifest.get("items", 0) * len(manifest.get("seeds", []))
    if len(pr.get("rows", [])) != expected_rows:
        problems.append(f"row count {len(pr.get('rows', []))} != {expected_rows}")

    # 3. the (item_id, seed) set of PR differs from the baseline's
    pr_pairs = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows", [])}
    base_pairs = {(r.get("item_id"), r.get("seed")) for r in base.get("rows", [])}
    if pr_pairs != base_pairs:
        problems.append("item_id and seed pairs differ from baseline")

    # 4. pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is None
    if pr.get("evaluator_failures"):
        problems.append(f"evaluator_failures non-empty: {len(pr['evaluator_failures'])} failure(s)")
    graded_metrics = {m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS}
    for r in pr.get("rows", []):
        for gm in graded_metrics:
            if gm not in r or r[gm] is None:
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} missing value for graded metric {gm}")
                break

    # 5. base_spec given and a threshold in spec is LOOSER than in base_spec for the same eval-set version
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        base_metrics = {m["id"]: m for m in base_spec.get("metrics", [])}
        curr_metrics = {m["id"]: m for m in spec.get("metrics", [])}
        for mid, bm in base_metrics.items():
            if mid not in curr_metrics:
                problems.append(f"metric {mid} dropped from spec")
                continue
            cm = curr_metrics[mid]
            if bm.get("blocking") and not cm.get("blocking"):
                problems.append(f"metric {mid} blocking was removed")
            bth = bm.get("threshold", {})
            cth = cm.get("threshold", {})
            if "min" in bth and cth.get("min", float("-inf")) < bth["min"]:
                problems.append(f"metric {mid} min threshold loosened: {cth.get('min')} < {bth['min']}")
            if "max" in bth and cth.get("max", float("inf")) > bth["max"]:
                problems.append(f"metric {mid} max threshold loosened: {cth.get('max')} > {bth['max']}")
            if bth.get("no_significant_drop") and not cth.get("no_significant_drop"):
                problems.append(f"metric {mid} no_significant_drop dropped")

        base_slices = {s["name"]: s for s in base_spec.get("slices", [])}
        curr_slices = {s["name"]: s for s in spec.get("slices", [])}
        for sname, bs_item in base_slices.items():
            if sname not in curr_slices:
                problems.append(f"slice {sname} dropped from spec")
                continue
            cs_item = curr_slices[sname]
            if bs_item.get("blocking") and not cs_item.get("blocking"):
                problems.append(f"slice {sname} blocking was removed")
            if "min" in bs_item and cs_item.get("min", float("-inf")) < bs_item["min"]:
                problems.append(f"slice {sname} min threshold loosened")
            if bs_item.get("no_significant_drop") and not cs_item.get("no_significant_drop"):
                problems.append(f"slice {sname} no_significant_drop dropped")

    # 6. an item's slice tags in PR rows differ from the baseline's
    base_item_slices = {r["item_id"]: sorted(r.get("slices") or []) for r in base.get("rows", [])}
    for r in pr.get("rows", []):
        iid = r.get("item_id")
        if iid in base_item_slices:
            if sorted(r.get("slices") or []) != base_item_slices[iid]:
                problems.append(f"item {iid} slice tags modified: {r.get('slices')} != {base_item_slices[iid]}")
                break

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices", []):
        name = sl["name"]
        mid = sl["metric"]
        min_val = sl.get("min")
        blocking = sl.get("blocking", False)
        slice_pr = per_item(pr, mid, slice_name=name)
        slice_base = per_item(base, mid, slice_name=name)
        if not slice_pr:
            continue
        val = sum(slice_pr.values()) / len(slice_pr)
        verdict, note = "ok", ""
        if min_val is not None and val < min_val:
            verdict = "fail"
        if sl.get("no_significant_drop"):
            keys = sorted(set(slice_pr) & set(slice_base))
            if keys:
                d, lo, hi = stats.paired_bootstrap(
                    [slice_pr[k] for k in keys],
                    [slice_base[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        tag = f"slice:{name}/{mid}"
        if verdict != "ok" and blocking:
            blocked.append(tag)
        lbl = "ok" if verdict == "ok" else ("BLOCK" if blocking else "warn")
        lines.append(f"  {tag:<22} {val!s:<8} {json.dumps(sl):<40} {note:<28} {lbl}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
