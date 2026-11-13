"""SQLite storage: target tables, rejects, run log, and idempotent upserts."""
import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    country     TEXT,
    created_at  TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    source_file TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id    TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    status      TEXT NOT NULL,
    amount      TEXT NOT NULL,
    currency    TEXT NOT NULL,
    event_ts    TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    source_file TEXT NOT NULL
);

-- append-only: every accepted event is kept, nothing is overwritten
CREATE TABLE IF NOT EXISTS orders_history (
    order_id    TEXT NOT NULL,
    event_ts    TEXT NOT NULL,
    status      TEXT NOT NULL,
    amount      TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    source_file TEXT NOT NULL,
    PRIMARY KEY (order_id, event_ts)
);

CREATE TABLE IF NOT EXISTS rejects (
    run_id        TEXT NOT NULL,
    source_file   TEXT NOT NULL,
    row_number    INTEGER NOT NULL,
    reject_reason TEXT NOT NULL,
    detail        TEXT,
    raw_record    TEXT,
    PRIMARY KEY (run_id, row_number, reject_reason)
);

CREATE TABLE IF NOT EXISTS run_log (
    run_id         TEXT PRIMARY KEY,
    source_file    TEXT NOT NULL,
    contract_version INTEGER,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    status         TEXT NOT NULL,
    rows_in        INTEGER DEFAULT 0,
    rows_accepted  INTEGER DEFAULT 0,
    rows_rejected  INTEGER DEFAULT 0,
    rows_duplicate INTEGER DEFAULT 0,
    failure_reason TEXT
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def start_run(conn, run_id, source_file, contract_version):
    # INSERT OR REPLACE lets a retried run reuse the same run_id.
    conn.execute(
        "INSERT OR REPLACE INTO run_log (run_id, source_file, contract_version, started_at, status) "
        "VALUES (?, ?, ?, ?, 'running')",
        (run_id, source_file, contract_version, now_iso()),
    )
    conn.commit()


def finish_run(conn, run_id, status, rows_in=0, accepted=0, rejected=0,
               duplicate=0, failure_reason=None):
    conn.execute(
        "UPDATE run_log SET ended_at=?, status=?, rows_in=?, rows_accepted=?, "
        "rows_rejected=?, rows_duplicate=?, failure_reason=? WHERE run_id=?",
        (now_iso(), status, rows_in, accepted, rejected, duplicate,
         failure_reason, run_id),
    )
    conn.commit()


def write_reject(conn, run_id, source_file, row_number, reason, detail, raw):
    conn.execute(
        "INSERT OR REPLACE INTO rejects VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, source_file, row_number, reason, detail,
         json.dumps(raw, default=str)),
    )


def upsert_customer(conn, row, run_id, source_file):
    conn.execute(
        """INSERT INTO customers (customer_id, email, country, created_at, run_id, source_file)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(customer_id) DO UPDATE SET
             email=excluded.email, country=excluded.country,
             created_at=excluded.created_at, run_id=excluded.run_id,
             source_file=excluded.source_file""",
        (row["customer_id"], row["email"], row.get("country") or None,
         row["created_at"], run_id, source_file),
    )


def customer_exists(conn, customer_id):
    cur = conn.execute("SELECT 1 FROM customers WHERE customer_id=?", (customer_id,))
    return cur.fetchone() is not None


def get_order_ts(conn, order_id):
    cur = conn.execute("SELECT event_ts FROM orders WHERE order_id=?", (order_id,))
    r = cur.fetchone()
    return r[0] if r else None


def upsert_order(conn, row, run_id, source_file):
    """Insert or update an order. Only overwrite if the incoming event is newer."""
    conn.execute(
        """INSERT INTO orders (order_id, customer_id, status, amount, currency, event_ts, run_id, source_file)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(order_id) DO UPDATE SET
             customer_id=excluded.customer_id, status=excluded.status,
             amount=excluded.amount, currency=excluded.currency,
             event_ts=excluded.event_ts, run_id=excluded.run_id,
             source_file=excluded.source_file
           WHERE excluded.event_ts > orders.event_ts""",
        (row["order_id"], row["customer_id"], row["status"], row["amount"],
         row["currency"], row["event_ts"], run_id, source_file),
    )
    conn.execute(
        "INSERT OR IGNORE INTO orders_history VALUES (?, ?, ?, ?, ?, ?)",
        (row["order_id"], row["event_ts"], row["status"], row["amount"],
         run_id, source_file),
    )