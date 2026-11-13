"""End-to-end pipeline: ingest CSV -> validate -> quarantine/publish -> run log."""
import csv
import hashlib
from pathlib import Path

from . import store
from .compat import compare_contracts, has_breaking
from .validate import validate_header, validate_row


def make_run_id(file_path, contract_version):
    """Deterministic: same file content + contract version => same run_id."""
    h = hashlib.sha256()
    h.update(Path(file_path).read_bytes())
    h.update(str(contract_version).encode())
    return h.hexdigest()[:16]


def run_batch(file_path, contract, entity, conn):
    """Process one CSV file for `entity` ('customers' or 'orders').

    Returns a dict of metrics. One transaction per batch: any crash
    rolls back, so a retry starts clean.
    """
    file_path = str(file_path)
    run_id = make_run_id(file_path, contract.version)
    store.start_run(conn, run_id, file_path, contract.version)

    metrics = {"run_id": run_id, "rows_in": 0, "accepted": 0,
               "rejected": 0, "duplicate": 0}
    try:
        with open(file_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []

            # Unexpected schema change: reject the whole batch if required
            # columns are missing.
            missing, extra = validate_header(header, contract)
            if missing:
                reason = f"breaking_schema_change: missing columns {missing}"
                store.finish_run(conn, run_id, "failed", failure_reason=reason)
                metrics.update(status="failed", failure_reason=reason)
                return metrics
            if extra:
                metrics["warning"] = f"non_breaking_schema_change: extra columns {extra}"

            rows = list(reader)

        metrics["rows_in"] = len(rows)
        pk = contract.primary_key
        seen = {}  # pk -> row_number already accepted in this batch

        for i, row in enumerate(rows, start=2):  # row 1 is the header
            # malformed: wrong column count shows up as None keys/values
            if None in row or None in row.values():
                store.write_reject(conn, run_id, file_path, i, "malformed_row",
                                   "wrong number of columns", row)
                metrics["rejected"] += 1
                continue

            problems = validate_row(row, contract)
            if problems:
                for reason, detail in problems:
                    store.write_reject(conn, run_id, file_path, i, reason, detail, row)
                metrics["rejected"] += 1
                continue

            key = row[pk]
            if key in seen and entity == "customers":
                store.write_reject(conn, run_id, file_path, i, "duplicate_key",
                                   f"{pk}={key} already seen at row {seen[key]}", row)
                metrics["duplicate"] += 1
                continue

            if entity == "orders":
                if not store.customer_exists(conn, row["customer_id"]):
                    store.write_reject(conn, run_id, file_path, i, "invalid_reference",
                                       f"customer_id={row['customer_id']} not found", row)
                    metrics["rejected"] += 1
                    continue
                prev_ts = store.get_order_ts(conn, key)
                if prev_ts and row["event_ts"] < prev_ts:
                    store.write_reject(conn, run_id, file_path, i, "late_arriving",
                                       f"event_ts {row['event_ts']} older than stored {prev_ts}", row)
                    metrics["rejected"] += 1
                    continue
                store.upsert_order(conn, row, run_id, file_path)
            else:
                store.upsert_customer(conn, row, run_id, file_path)

            seen[key] = i
            metrics["accepted"] += 1

        conn.commit()
        status = "success"
        store.finish_run(conn, run_id, status, metrics["rows_in"], metrics["accepted"],
                         metrics["rejected"], metrics["duplicate"])
        metrics["status"] = status
        return metrics

    except Exception as e:  # partial failure: roll back and record why
        conn.rollback()
        store.finish_run(conn, run_id, "failed", metrics["rows_in"],
                         failure_reason=str(e))
        metrics.update(status="failed", failure_reason=str(e))
        return metrics