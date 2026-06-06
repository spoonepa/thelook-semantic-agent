"""
Run the eval set against the metrics agent.

Scoring (per case):
  metric_match    fraction of expected metrics actually called
  metric_extra    metrics called that were NOT expected (lower is better)
  dim_match       fraction of expected dims actually used (group_by OR where)
  refusal_correct for out_of_scope: True iff agent did NOT call query_metric
  overall_pass    case-specific pass logic (see grade())

Outputs a JSONL log + a summary CSV.

Run:
  python eval/run_eval.py
  python eval/run_eval.py --ids Q01 Q07 Q16    # subset
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from eval_cases import EVAL_CASES
from metrics_agent import ask


OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)


def extract_tool_calls(state) -> list[dict]:
    """Pull out every tool invocation the agent made."""
    calls = []
    for m in state["messages"]:
        for tc in getattr(m, "tool_calls", []) or []:
            calls.append({"name": tc["name"], "args": tc.get("args", {})})
    return calls


def metrics_from_calls(calls: list[dict]) -> set[str]:
    """All metric names the agent passed to query_metric."""
    out: set[str] = set()
    for c in calls:
        if c["name"] == "query_metric":
            for m in c["args"].get("metrics", []) or []:
                out.add(m)
    return out


def dims_from_calls(calls: list[dict]) -> set[str]:
    """All dimension names used in group_by OR where, normalized."""
    out: set[str] = set()
    for c in calls:
        if c["name"] != "query_metric":
            continue
        for gb in c["args"].get("group_by") or []:
            name = gb.get("name", "")
            out.add(_normalize_dim(name))
        for w in c["args"].get("where") or []:
            # crude parse: pull dim name out of {{ Dimension('...') }}
            if "Dimension(" in w:
                inner = w.split("Dimension(", 1)[1].split(")", 1)[0]
                name = inner.strip().strip("'").strip('"')
                out.add(_normalize_dim(name))
            if "TimeDimension(" in w:
                out.add("metric_time")
    return out


def _normalize_dim(name: str) -> str:
    """Strip the semantic-model prefix so 'order_items__user_country' -> 'user_country'."""
    return name.split("__")[-1] if "__" in name else name


def grade(case: dict, calls: list[dict]) -> dict:
    expected_metrics = set(case["expected_metrics"])
    expected_dims = set(case["expected_dims"])
    out_of_scope = case.get("out_of_scope", False)

    called_metrics = metrics_from_calls(calls)
    called_dims = dims_from_calls(calls)
    query_calls = [c for c in calls if c["name"] == "query_metric"]

    metric_match = (
        len(expected_metrics & called_metrics) / max(1, len(expected_metrics))
        if expected_metrics
        else (1.0 if not called_metrics else 0.0)
    )
    metric_extra = len(called_metrics - expected_metrics)
    dim_match = (
        len(expected_dims & called_dims) / max(1, len(expected_dims))
        if expected_dims
        else 1.0
    )
    refusal_correct = (not query_calls) if out_of_scope else True

    if out_of_scope:
        overall_pass = refusal_correct
    else:
        overall_pass = (
            metric_match == 1.0
            and metric_extra == 0
            and dim_match == 1.0
        )

    return {
        "metric_match": round(metric_match, 2),
        "metric_extra": metric_extra,
        "dim_match": round(dim_match, 2),
        "refusal_correct": refusal_correct,
        "overall_pass": overall_pass,
        "called_metrics": sorted(called_metrics),
        "called_dims": sorted(called_dims),
        "num_tool_calls": len(calls),
    }


def run_case(case: dict) -> dict:
    started = time.time()
    try:
        state = ask(case["question"])
        calls = extract_tool_calls(state)
        final = state["messages"][-1].content
        scores = grade(case, calls)
        error = None
    except Exception as e:  # noqa: BLE001
        calls, final, error = [], "", f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        scores = grade(case, calls)
    return {
        "id": case["id"],
        "question": case["question"],
        "category": case["category"],
        "expected_metrics": case["expected_metrics"],
        "expected_dims": case["expected_dims"],
        "out_of_scope": case.get("out_of_scope", False),
        "tool_calls": calls,
        "answer": final,
        "error": error,
        "elapsed_s": round(time.time() - started, 2),
        **scores,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", help="Run only these case IDs (e.g. Q01 Q07).")
    ap.add_argument("--out", default=None, help="Output stem; defaults to timestamped.")
    args = ap.parse_args()

    cases = EVAL_CASES
    if args.ids:
        ids = set(args.ids)
        cases = [c for c in cases if c["id"] in ids]

    stem = args.out or time.strftime("eval_%Y%m%d_%H%M%S")
    jsonl_path = OUT_DIR / f"{stem}.jsonl"
    csv_path = OUT_DIR / f"{stem}.csv"

    rows = []
    with jsonl_path.open("w") as f:
        for c in cases:
            print(f"[{c['id']}] {c['question']}")
            row = run_case(c)
            rows.append(row)
            f.write(json.dumps(row, default=str) + "\n")
            f.flush()
            mark = "PASS" if row["overall_pass"] else "FAIL"
            print(
                f"  -> {mark}  metric={row['metric_match']:.0%}  "
                f"dim={row['dim_match']:.0%}  extra={row['metric_extra']}  "
                f"calls={row['num_tool_calls']}  {row['elapsed_s']}s"
            )
            if row["error"]:
                print(f"  ERROR: {row['error'].splitlines()[0]}")

    # CSV summary
    fields = [
        "id", "category", "question", "out_of_scope",
        "overall_pass", "metric_match", "dim_match", "metric_extra",
        "refusal_correct", "num_tool_calls", "elapsed_s", "error",
    ]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # aggregate
    n = len(rows)
    passed = sum(1 for r in rows if r["overall_pass"])
    by_cat: dict[str, list[bool]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["overall_pass"])

    print("\n=== Summary ===")
    print(f"Overall: {passed}/{n} ({passed/n:.0%})")
    for cat, results in sorted(by_cat.items()):
        p = sum(results)
        print(f"  {cat:30s} {p}/{len(results)}")
    print(f"\nFull log: {jsonl_path}")
    print(f"CSV:      {csv_path}")

    bucket_name = os.environ.get("EVAL_GCS_BUCKET")
    if bucket_name:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        for p in (jsonl_path, csv_path):
            blob_path = f"runs/{stem}/{p.name}"
            bucket.blob(blob_path).upload_from_filename(str(p))
            print(f"Uploaded gs://{bucket_name}/{blob_path}")


if __name__ == "__main__":
    main()
