"""Load data contracts from YAML into typed Python objects."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

ALLOWED_TYPES = {"string", "integer", "decimal", "timestamp", "boolean"}


class ContractError(Exception):
    """Raised when a contract file is invalid."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    allowed_values: Optional[tuple] = None
    min: Optional[float] = None
    max: Optional[float] = None
    references: Optional[str] = None  # format: "table.column"


@dataclass(frozen=True)
class Contract:
    name: str
    version: int
    columns: tuple = field(default_factory=tuple)

    def column_names(self):
        return [c.name for c in self.columns]

    def get(self, name):
        for c in self.columns:
            if c.name == name:
                return c
        return None

    @property
    def primary_key(self):
        pks = [c.name for c in self.columns if c.primary_key]
        return pks[0] if pks else None


def load_contract(path):
    """Read a YAML contract file and return a Contract."""
    path = Path(path)
    if not path.exists():
        raise ContractError(f"Contract file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ContractError(f"{path}: top level must be a mapping")
    for key in ("name", "version", "columns"):
        if key not in raw:
            raise ContractError(f"{path}: missing '{key}'")

    columns = []
    seen = set()
    for item in raw["columns"]:
        if "name" not in item or "type" not in item:
            raise ContractError(f"{path}: every column needs 'name' and 'type'")
        if item["type"] not in ALLOWED_TYPES:
            raise ContractError(
                f"{path}: column '{item['name']}' has unknown type '{item['type']}'"
            )
        if item["name"] in seen:
            raise ContractError(f"{path}: duplicate column '{item['name']}'")
        seen.add(item["name"])

        allowed = item.get("allowed_values")
        columns.append(
            Column(
                name=item["name"],
                type=item["type"],
                nullable=item.get("nullable", True),
                primary_key=item.get("primary_key", False),
                allowed_values=tuple(allowed) if allowed else None,
                min=item.get("min"),
                max=item.get("max"),
                references=item.get("references"),
            )
        )

    return Contract(
        name=raw["name"], version=int(raw["version"]), columns=tuple(columns)
    )