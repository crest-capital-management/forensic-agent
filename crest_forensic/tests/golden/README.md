# Golden dataset

This directory holds hand-checked "answer key" files used to validate that
ingested data actually matches what's printed in the real annual report
(Build Plan section 14: "Answer key test").

**These files must be filled in by hand from a real annual report — nothing
in this repo invents or assumes real company figures.** `tcs_golden.yaml` is
not included yet; `test_golden.py::test_tcs_matches_golden_dataset` skips
itself with a clear message until it exists.

## Format

```yaml
company: TCS
sc_id: TCS
years:
  FY2025:
    revenue_from_operations: {value: 123456.7, unit: "INR crore", page: 118}
    profit_after_tax: {value: 12345.6, unit: "INR crore", page: 120}
    cash_flow_from_operations: {value: 45678.9, unit: "INR crore", page: 145}
    trade_receivables: {value: 23456.7, unit: "INR crore", page: 200}
    total_assets: {value: 98765.4, unit: "INR crore", page: 199}
  FY2024:
    ...
  FY2023:
    ...
```

`value` is exactly what's printed on the cited `page`. `unit` is whatever
unit the report actually uses ("INR crore" is typical for large-cap Indian
filings) — the comparison converts it to absolute INR before comparing
against the normalized, ingested value.
