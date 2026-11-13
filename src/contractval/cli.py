"""CLI: run a batch, reconcile against labels, report timing."""
import argparse
import csv
import json
import time
from pathlib import Path

from .contract import load_contract
from .pipeline import run_batch
from .store import connect


def reconcile(conn, labels_path, orders_metrics):
    """Compare actual rejects/accepts with the separate expected-labels file."""
    expected = {}
    with open(labels_path, newline="") as f:
        for r in csv.DictReader(f):
            expected[int(r["row_number"])] = r["expected_reject_reason"]

    rejected = {}
    for row_number, reason in conn.execute(
        "SELECT row_number, reject_reason FROM rejects WHERE run_id=?",
        (orders_metrics["run_id"],),
    ):
        rejected.setdefault(row_number, reason)

    mismatches = []
    for rn, exp in expected.items():
        got = rejected.get(rn, "valid")
        if got != exp:
            mismatches.append((rn, exp, got))

    exp_valid = sum(1 for v in expected.values() if v == "valid")
    actual_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    return {
        "rows_in": orders_metrics["rows_in"],
        "accepted": orders_metrics["accepted"],
        "rejected": orders_metrics["rejected"],
        "accepted_plus_rejected_equals_rows_in":
            orders_metrics["accepted"] + orders_metrics["rejected"]
            + orders_metrics["duplicate"] == orders_metrics["rows_in"],
        "expected_valid": exp_valid,
        "orders_in_target": actual_orders,
        "label_mismatches": len(mismatches),
        "first_mismatches": mismatches[:5],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/generated")
    ap.add_argument("--db", default="out/pipeline.db")
    ap.add_argument("--report", default="out/validation_report.json")
    a = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(a.db)
    cc = load_contract(root / "contracts/customers_v1.yaml")
    oc = load_contract(root / "contracts/orders_v1.yaml")
    d = Path(a.data_dir)

    t0 = time.perf_counter()
    cm = run_batch(d / "customers.csv", cc, "customers", conn)
    om = run_batch(d / "orders.csv", oc, "orders", conn)
    secs = time.perf_counter() - t0

    report = {"customers": cm, "orders": om,
              "seconds": round(secs, 3),
              "rows_per_second": round(om["rows_in"] / secs) if secs else None}
    labels = d / "expected_labels.csv"
    if labels.exists():
        report["reconciliation"] = reconcile(conn, labels, om)

    Path(a.report).write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()