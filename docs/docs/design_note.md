# Design and trade-off note

## Choices

- **SQLite**: no setup or credentials, transactional, and supports `INSERT ... ON CONFLICT`. It keeps the project runnable from a clean clone. At scale I would move to a warehouse or Postgres.
- **YAML contracts**: readable, easy to diff between versions, which is what the compatibility checker does.
- **One transaction per batch**: a crash rolls the batch back, so retrying the same file is safe. Cost: a very large file holds one long transaction.
- **Deterministic run_id** (hash of file content + contract version): the same input maps to the same run, which makes reruns traceable and idempotent.
- **Upsert with a timestamp guard**: an older event never overwrites a newer one, so out-of-order and late data cannot corrupt current state. Late rows are also written to `rejects` as `late_arriving` so they stay visible.
- **orders_history**: append-only, so changes are kept instead of silently overwritten.
- **Breaking vs non-breaking**: a missing contract column fails the whole batch; extra columns only warn. Widening integer to decimal is treated as non-breaking. This is a judgment call and is documented in the README.
- **Amount stored as text**: avoids float rounding; validated as a decimal.

## Known limitations

- The whole file is read into memory.
- Duplicate order ids inside one batch are not flagged as `duplicate_key`; the later row simply updates the earlier one if its event_ts is newer or equal. Customer duplicates are flagged and the first row is kept.
- Only the first reject reason matters for reconciliation, though every failing rule is recorded in `rejects`.
- Contract version is chosen by the caller.
- Timestamps are compared as ISO-8601 strings, which is correct only when all use the same UTC format.

## At scale

Chunked or streaming reads, batched inserts with `executemany`, Parquet input, a warehouse target, and a contract registry that picks the version automatically.