"""Seeded synthetic data generator. Expected labels go in a SEPARATE file."""
import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


def generate(out_dir, rows=1000, seed=42):
    rng = random.Random(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n_cust = max(10, rows // 10)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def ts(seconds):
        return (base + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(out / "customers.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "email", "country", "created_at"])
        for i in range(n_cust):
            w.writerow([f"c{i}", f"user{i}@example.com",
                        rng.choice(["IN", "US", "DE", ""]), ts(i)])

    labels = []
    with open(out / "orders.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "customer_id", "status", "amount", "currency", "event_ts"])
        for i in range(rows):
            cid = f"c{rng.randrange(n_cust)}"
            status = rng.choice(["placed", "shipped", "cancelled"])
            amount = f"{rng.uniform(0, 500):.2f}"
            currency = rng.choice(["INR", "USD", "EUR"])
            t = ts(10_000 + i * 10)
            label = "valid"
            r = rng.random()
            if r < 0.02:
                cid, label = "c_missing", "invalid_reference"
            elif r < 0.04:
                status, label = "lost", "bad_value"
            elif r < 0.06:
                amount, label = "-1.00", "out_of_range"
            elif r < 0.08:
                amount, label = "", "missing_required"
            elif r < 0.10:
                t, label = "not-a-date", "bad_type"
            elif r < 0.12:
                amount = "0"  # boundary: valid
            w.writerow([f"o{i}", cid, status, amount, currency, t])
            labels.append((i + 2, f"o{i}", label))  # line 1 is the header

    with open(out / "expected_labels.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["row_number", "order_id", "expected_reject_reason"])
        w.writerows(labels)
    return n_cust, rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/generated")
    a = ap.parse_args()
    print(generate(a.out, a.rows, a.seed))