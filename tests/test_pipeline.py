from pathlib import Path

import pytest

from contractval import store
from contractval.compat import compare_contracts, has_breaking
from contractval.contract import load_contract
from contractval.pipeline import run_batch
from contractval.store import connect

ROOT = Path(__file__).resolve().parent.parent
CUST_HDR = "customer_id,email,country,created_at\n"
ORD_HDR = "order_id,customer_id,status,amount,currency,event_ts\n"


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture
def cc():
    return load_contract(ROOT / "contracts/customers_v1.yaml")


@pytest.fixture
def oc():
    return load_contract(ROOT / "contracts/orders_v1.yaml")


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def seed_customer(tmp_path, conn, cc):
    p = write(tmp_path, "cust.csv", CUST_HDR + "c1,a@x.com,IN,2026-01-01T00:00:00Z\n")
    return run_batch(p, cc, "customers", conn)


def reasons(conn):
    return [r[0] for r in conn.execute("select reject_reason from rejects")]


def count(conn, table):
    return conn.execute(f"select count(*) from {table}").fetchone()[0]


def test_happy_path(tmp_path, conn, cc, oc):
    seed_customer(tmp_path, conn, cc)
    p = write(tmp_path, "o.csv", ORD_HDR + "o1,c1,placed,10.50,INR,2026-01-02T10:00:00Z\n")
    m = run_batch(p, oc, "orders", conn)
    assert m["status"] == "success" and m["accepted"] == 1 and m["rejected"] == 0
    assert count(conn, "orders") == 1


def test_empty_batch(tmp_path, conn, oc):
    p = write(tmp_path, "o.csv", ORD_HDR)
    m = run_batch(p, oc, "orders", conn)
    assert m["status"] == "success" and m["rows_in"] == 0


def test_malformed_row(tmp_path, conn, cc, oc):
    seed_customer(tmp_path, conn, cc)
    p = write(tmp_path, "o.csv", ORD_HDR + "o1,c1,placed\n")
    m = run_batch(p, oc, "orders", conn)
    assert m["rejected"] == 1 and "malformed_row" in reasons(conn)


def test_duplicate_key_in_batch(tmp_path, conn, cc):
    p = write(tmp_path, "c.csv", CUST_HDR
              + "c1,a@x.com,IN,2026-01-01T00:00:00Z\n"
              + "c1,b@x.com,IN,2026-01-02T00:00:00Z\n")
    m = run_batch(p, cc, "customers", conn)
    assert m["accepted"] == 1 and m["duplicate"] == 1
    assert count(conn, "customers") == 1


def test_null_in_required_field(tmp_path, conn, cc):
    p = write(tmp_path, "c.csv", CUST_HDR + "c1,,IN,2026-01-01T00:00:00Z\n")
    m = run_batch(p, cc, "customers", conn)
    assert m["rejected"] == 1 and "missing_required" in reasons(conn)


def test_breaking_schema_change_rejects_batch(tmp_path, conn, cc, oc):
    seed_customer(tmp_path, conn, cc)
    p = write(tmp_path, "o.csv",
              "order_id,customer_id,status,amount,event_ts\n"
              "o1,c1,placed,10,2026-01-02T10:00:00Z\n")
    m = run_batch(p, oc, "orders", conn)
    assert m["status"] == "failed"
    assert m["failure_reason"].startswith("breaking_schema_change")
    assert count(conn, "orders") == 0


def test_non_breaking_schema_change_warns(tmp_path, conn, cc, oc):
    seed_customer(tmp_path, conn, cc)
    p = write(tmp_path, "o.csv",
              "order_id,customer_id,status,amount,currency,event_ts,coupon_code\n"
              "o1,c1,placed,10,INR,2026-01-02T10:00:00Z,SAVE10\n")
    m = run_batch(p, oc, "orders", conn)
    assert m["status"] == "success" and "warning" in m and m["accepted"] == 1


def test_invalid_reference_key(tmp_path, conn, cc, oc):
    seed_customer(tmp_path, conn, cc)
    p = write(tmp_path, "o.csv", ORD_HDR + "o1,c9,placed,10,INR,2026-01-02T10:00:00Z\n")
    m = run_batch(p, oc, "orders", conn)
    assert m["rejected"] == 1 and "invalid_reference" in reasons(conn)


def test_rerun_same_input_is_idempotent(tmp_path, conn, cc, oc):
    seed_customer(tmp_path, conn, cc)
    p = write(tmp_path, "o.csv", ORD_HDR + "o1,c1,placed,10,INR,2026-01-02T10:00:00Z\n")
    m1 = run_batch(p, oc, "orders", conn)
    m2 = run_batch(p, oc, "orders", conn)
    assert m1["run_id"] == m2["run_id"]
    assert count(conn, "orders") == 1
    assert count(conn, "orders_history") == 1
    assert count(conn, "run_log") == 2  # one per file: customers + orders


def test_late_arriving_event_does_not_overwrite(tmp_path, conn, cc, oc):
    seed_customer(tmp_path, conn, cc)
    new = write(tmp_path, "new.csv", ORD_HDR + "o1,c1,shipped,10,INR,2026-01-03T10:00:00Z\n")
    old = write(tmp_path, "old.csv", ORD_HDR + "o1,c1,placed,10,INR,2026-01-02T10:00:00Z\n")
    run_batch(new, oc, "orders", conn)
    m = run_batch(old, oc, "orders", conn)
    assert m["rejected"] == 1 and "late_arriving" in reasons(conn)
    assert conn.execute("select status from orders").fetchone()[0] == "shipped"


def test_amount_boundary(tmp_path, conn, cc, oc):
    seed_customer(tmp_path, conn, cc)
    p = write(tmp_path, "o.csv", ORD_HDR
              + "o1,c1,placed,0,INR,2026-01-02T10:00:00Z\n"
              + "o2,c1,placed,-0.01,INR,2026-01-02T11:00:00Z\n")
    m = run_batch(p, oc, "orders", conn)
    assert m["accepted"] == 1 and m["rejected"] == 1
    assert conn.execute("select order_id from orders").fetchall() == [("o1",)]


def test_partial_failure_then_retry(tmp_path, conn, cc, oc, monkeypatch):
    seed_customer(tmp_path, conn, cc)
    p = write(tmp_path, "o.csv", ORD_HDR + "o1,c1,placed,10,INR,2026-01-02T10:00:00Z\n")

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "upsert_order", boom)
    m = run_batch(p, oc, "orders", conn)
    assert m["status"] == "failed" and "disk full" in m["failure_reason"]
    assert count(conn, "orders") == 0

    monkeypatch.undo()  # the problem is fixed; retry the same file
    m = run_batch(p, oc, "orders", conn)
    assert m["status"] == "success" and count(conn, "orders") == 1


def test_compat_v1_to_v2_flags_breaking():
    a = load_contract(ROOT / "contracts/orders_v1.yaml")
    b = load_contract(ROOT / "contracts/orders_v2.yaml")
    changes = compare_contracts(a, b)
    assert has_breaking(changes)
    kinds = {(c.change, c.severity) for c in changes}
    assert ("column_removed", "breaking") in kinds
    assert ("column_added", "non_breaking") in kinds


def test_compat_identical_contracts_have_no_changes():
    a = load_contract(ROOT / "contracts/orders_v1.yaml")
    assert compare_contracts(a, a) == []