# Data dictionary

All timestamps are ISO-8601 UTC text (e.g. `2026-01-02T10:00:00Z`). All names are snake_case.

## customers (current state, grain: one row per customer)

| Column | Type | Null | Rules |
|---|---|---|---|
| customer_id | text | no | Primary key |
| email | text | no | Required |
| country | text | yes | Optional |
| created_at | text (timestamp) | no | ISO-8601 |
| run_id | text | no | Run that last wrote the row |
| source_file | text | no | File that last wrote the row |

## orders (current state, grain: one row per order)

| Column | Type | Null | Rules |
|---|---|---|---|
| order_id | text | no | Primary key |
| customer_id | text | no | Foreign key to customers.customer_id |
| status | text | no | One of placed, shipped, cancelled |
| amount | text (decimal) | no | Must be >= 0 (0 valid, -0.01 invalid) |
| currency | text | no | One of INR, USD, EUR |
| event_ts | text (timestamp) | no | Row is only overwritten by a newer event_ts |
| run_id | text | no | Run that last wrote the row |
| source_file | text | no | File that last wrote the row |

Amount is stored as text to avoid float rounding; it is parsed as a decimal during validation.

## orders_history (append-only, grain: one row per order event)

| Column | Type | Null | Rules |
|---|---|---|---|
| order_id | text | no | Part of primary key |
| event_ts | text | no | Part of primary key |
| status | text | no | |
| amount | text | no | |
| run_id | text | no | |
| source_file | text | no | |

Inserted with INSERT OR IGNORE, so a rerun never duplicates an event.

## rejects (quarantine, grain: one row per row and reason)

| Column | Type | Null | Rules |
|---|---|---|---|
| run_id | text | no | Part of primary key |
| source_file | text | no | Traceability to input file |
| row_number | integer | no | Line number in the file (header is line 1); part of primary key |
| reject_reason | text | no | malformed_row, missing_required, bad_type, bad_value, out_of_range, duplicate_key, invalid_reference, late_arriving; part of primary key |
| detail | text | yes | Human-readable explanation |
| raw_record | text | yes | Original row as JSON |

## run_log (one row per run)

| Column | Type | Null | Rules |
|---|---|---|---|
| run_id | text | no | Primary key; hash of file content + contract version |
| source_file | text | no | |
| contract_version | integer | yes | |
| started_at | text | no | |
| ended_at | text | yes | Empty while running |
| status | text | no | running, success, failed |
| rows_in | integer | no | Data rows read |
| rows_accepted | integer | no | |
| rows_rejected | integer | no | |
| rows_duplicate | integer | no | |
| failure_reason | text | yes | Set when status is failed |

Reconciliation: rows_in = rows_accepted + rows_rejected + rows_duplicate.