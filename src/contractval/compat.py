"""Compare two contracts and classify each change as breaking or non-breaking."""
from dataclasses import dataclass

BREAKING = "breaking"
NON_BREAKING = "non_breaking"

# Type changes that only widen the range of values are treated as safe.
WIDENING = {("integer", "decimal")}


@dataclass(frozen=True)
class Change:
    change: str
    column: str
    severity: str
    detail: str

    def to_dict(self):
        return {
            "change": self.change,
            "column": self.column,
            "severity": self.severity,
            "detail": self.detail,
        }


def compare_contracts(old, new):
    """Return a list of Change objects describing old -> new."""
    changes = []
    old_cols = {c.name: c for c in old.columns}
    new_cols = {c.name: c for c in new.columns}

    for name, o in old_cols.items():
        if name not in new_cols:
            changes.append(Change("column_removed", name, BREAKING,
                                  f"'{name}' no longer exists"))
            continue
        n = new_cols[name]

        if o.type != n.type:
            sev = NON_BREAKING if (o.type, n.type) in WIDENING else BREAKING
            changes.append(Change("type_changed", name, sev,
                                  f"{o.type} -> {n.type}"))

        if o.nullable and not n.nullable:
            changes.append(Change("nullable_to_required", name, BREAKING,
                                  "column is now required"))
        elif not o.nullable and n.nullable:
            changes.append(Change("required_to_nullable", name, NON_BREAKING,
                                  "column is now optional"))

        old_vals = set(o.allowed_values or ())
        new_vals = set(n.allowed_values or ())
        if o.allowed_values and n.allowed_values:
            removed = old_vals - new_vals
            added = new_vals - old_vals
            if removed:
                changes.append(Change("allowed_value_removed", name, BREAKING,
                                      f"removed {sorted(removed)}"))
            if added:
                changes.append(Change("allowed_value_added", name, NON_BREAKING,
                                      f"added {sorted(added)}"))
        elif o.allowed_values and not n.allowed_values:
            changes.append(Change("allowed_values_dropped", name, NON_BREAKING,
                                  "constraint removed"))
        elif not o.allowed_values and n.allowed_values:
            changes.append(Change("allowed_values_added", name, BREAKING,
                                  f"new restriction {sorted(new_vals)}"))

    for name, n in new_cols.items():
        if name not in old_cols:
            if n.nullable:
                changes.append(Change("column_added", name, NON_BREAKING,
                                      "new optional column"))
            else:
                changes.append(Change("required_column_added", name, BREAKING,
                                      "new required column"))
    return changes


def has_breaking(changes):
    return any(c.severity == BREAKING for c in changes)