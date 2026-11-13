# contract-validator

A small data-contract validator and loader. It defines column contracts (types, nullability, allowed values, keys), checks producer batches against them, reports **breaking vs non-breaking** schema changes, quarantines bad rows with full traceability, and publishes clean data to SQLite idempotently.

## Architecture

```
CSV batch --> header check --> row validation --> accepted --> orders / customers (upsert)
                  |                 |                      \-> orders_history (append-only)
          breaking change?       rejected rows
          fail whole batch       --> rejects table (run_id, source_file, row_number, reason, raw_record)
                  \_________________\__ run_log (status, counts, failure_reason)
```

Modules in `src/contractval/`:
- `contract.py`: loads YAML contracts into typed objects
- `compat.py`: compares two contract versions, classifies each change as breaking or non-breaking
- `validate.py`: header check and row-level rules (type, null, allowed values, range)
- `store.py`: SQLite schema, upserts, run log, rejects
- `pipeline.py`: ingest, validate, quarantine, publish
- `generator.py`: seeded synthetic data with a separate labels file
- `cli.py`: runs a batch, reconciles against labels, reports timing

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
# tests
pytest -v

# small sample
PYTHONPATH=src python -m contractval.cli --data-dir data/sample --report out/sample_report.json

# large run (100k orders)
PYTHONPATH=src python -m contractval.generator --rows 100000 --seed 42 --out data/generated_100k
rm -f out/pipeline.db
PYTHONPATH=src python -m contractval.cli --data-dir data/generated_100k --report out/report_100k.json
```

## Contracts and compatibility rules

| Change | Classification |
|---|---|
| Column removed | Breaking |
| Type changed (except integer to decimal) | Breaking |
| Nullable to required | Breaking |
| Allowed value removed | Breaking |
| New required column | Breaking |
| New nullable column | Non-breaking |
| Required to nullable | Non-breaking |
| Allowed value added | Non-breaking |
| integer to decimal (widening) | Non-breaking (documented choice) |

At load time, a file missing a contract column is a breaking change and the **whole batch is failed**. Extra columns are non-breaking: the batch loads and a warning is recorded.

## Row rules and reject reasons

`malformed_row`, `missing_required`, `bad_type`, `bad_value`, `out_of_range`, `duplicate_key`, `invalid_reference`, `late_arriving`. Every reject stores `run_id`, `source_file`, `row_number`, and the raw record.

## Idempotency, retry, restart, backfill

- `run_id` is a hash of file content plus contract version, so the same input always gets the same run.
- Orders are upserted on `order_id`; an older `event_ts` never overwrites a newer one.
- Each batch is one transaction: a crash rolls back and the retry starts clean.
- Rerunning the same file creates no duplicates (tested).
- Backfill means rerunning older files; the upsert plus the timestamp guard make that safe.
- `orders_history` is append-only, so changes are preserved rather than overwritten.

## Naming conventions

snake_case tables and columns, ISO-8601 UTC timestamps, explicit `run_id` and `source_file` on every loaded and rejected row.

## Testing

`pytest` runs 14 tests: happy path, empty batch, malformed row, duplicates, nulls, breaking and non-breaking schema change, invalid reference, rerun, late-arriving event, amount boundary (0 valid, -0.01 invalid), partial failure then retry, and compatibility checks.

## Performance

100,000 orders (+10,000 customers), single run on a laptop:

| | Seconds | Rows/sec |
|---|---|---|
| Baseline (SELECT per row for FK and late check) | 2.423 | 41,272 |
| Optimized (lookups loaded once per batch) | 2.010 | 49,756 |

Reconciliation after the optimized run: 90,090 accepted = 90,090 expected valid = 90,090 in the target; 0 label mismatches against `expected_labels.csv`.

## Known limitations

- Whole file is read into memory.
- Duplicate handling inside an orders batch relies on the upsert plus the timestamp guard; customer duplicates keep the first row.
- Only CSV input; SQLite as the single store.
- Contract version is chosen by the caller; no automatic version discovery.

## Possible next steps

Batch inserts with `executemany`, chunked reading for large files, Parquet input, contract registry with automatic version selection.