"""Validate individual rows and file headers against a contract."""
from datetime import datetime
from decimal import Decimal, InvalidOperation


def _parse(value, col_type):
    """Convert a raw string to its typed value, or raise ValueError."""
    if col_type == "string":
        return str(value)
    if col_type == "integer":
        return int(value)
    if col_type == "decimal":
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise ValueError(f"not a decimal: {value!r}")
    if col_type == "boolean":
        if str(value).lower() in ("true", "false", "1", "0"):
            return str(value).lower() in ("true", "1")
        raise ValueError(f"not a boolean: {value!r}")
    if col_type == "timestamp":
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    raise ValueError(f"unknown type {col_type}")


def is_blank(value):
    return value is None or str(value).strip() == ""


def validate_header(header, contract):
    """Return (missing_columns, unexpected_columns) for a file header."""
    expected = set(contract.column_names())
    got = set(header)
    return sorted(expected - got), sorted(got - expected)


def validate_row(row, contract):
    """Return a list of (reason, detail) problems. Empty list = valid."""
    problems = []
    for col in contract.columns:
        value = row.get(col.name)

        if is_blank(value):
            if not col.nullable:
                problems.append(("missing_required", f"{col.name} is empty"))
            continue

        try:
            typed = _parse(value, col.type)
        except (ValueError, TypeError):
            problems.append(("bad_type", f"{col.name}={value!r} is not {col.type}"))
            continue

        if col.allowed_values and str(typed) not in col.allowed_values:
            problems.append(("bad_value", f"{col.name}={value!r} not in {list(col.allowed_values)}"))

        if col.min is not None and col.type in ("integer", "decimal") and typed < col.min:
            problems.append(("out_of_range", f"{col.name}={value} below min {col.min}"))
        if col.max is not None and col.type in ("integer", "decimal") and typed > col.max:
            problems.append(("out_of_range", f"{col.name}={value} above max {col.max}"))
    return problems