from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class FieldMapping(BaseModel):
    standard_field: str
    statement_type: str  # income / balance_sheet / cash_flow / notes (Build Plan taxonomy)
    semantics: str  # flow / stock
    source_endpoint: str  # income / balance_sheet / cash_flow / ratios — the PHYSICAL RapidAPI
    # endpoint this comes from. Note cash_flow is a mislabeled endpoint that
    # actually returns an annual P&L statement (confirmed 2026-09-28) — it is
    # NOT a cash-flow statement, so this may differ from `statement_type`.
    item_name_contains: str | None = None  # exact "item[].name" match within a period
    provider_field: str | None = None  # fallback: dotted/bracket JSON path strategy
    unit_multiplier: float | None = None  # None = unit not confirmed yet
    # If set, this mapping applies ONLY to these bases (e.g. [standalone]). Used
    # when a provider's definition of a line is only trustworthy for one basis.
    bases: list[str] | None = None


class FieldMappingConfig(BaseModel):
    mapping_version: int
    fields: list[FieldMapping]

    def for_endpoint(self, source_endpoint: str) -> list[FieldMapping]:
        return [f for f in self.fields if f.source_endpoint == source_endpoint]


def load_field_mapping(path: str | Path) -> FieldMappingConfig:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return FieldMappingConfig.model_validate(raw)


DEFAULT_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "field_mapping_rapidapi.yaml"
)
