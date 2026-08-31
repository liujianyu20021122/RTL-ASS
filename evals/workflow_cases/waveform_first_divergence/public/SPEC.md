# FST first-divergence localization

`trace/priority_divergence.fst` is the failing trace for `rtl/priority_monitor.sv`. Do not edit the RTL or trace. Use a bounded machine-readable FST query to locate the earliest divergence between `priority_monitor_tb.expected_o` and `priority_monitor_tb.actual_o`, then map it to the responsible source behavior.

Create `artifacts/wave-divergence.json` by saving the helper's `wave diff` JSON. Also create `artifacts/diagnosis.json` containing exactly:

```json
{
  "schema_version": "1.0",
  "classification": "missing-no-request-default",
  "first_divergence_time": 20,
  "expected_value": "0",
  "actual_value": "1",
  "responsible_file": "rtl/priority_monitor.sv"
}
```

The time window must be bounded to include the first divergence. Evidence must bind the original FST hash and the bounded conversion metadata; reading a converted VCD without binding it to the FST is incomplete.
