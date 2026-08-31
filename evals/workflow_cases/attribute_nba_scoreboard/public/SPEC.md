# Registered pulse contract and diagnosis output

`rtl/registered_pulse.sv` is intended to register `valid_i` and `data_i` on each rising edge. Its active-low reset is synchronous and clears both outputs. The supplied test fails on the first transaction.

Determine whether the DUT or testbench is responsible. Change only the responsible source file, preserve the one-cycle registered behavior, and keep the test self-checking. Do not use an arbitrary `#` delay to hide a simulation-region race.

Reproduce the failure with `vvp <simulation> +DUMP`; the testbench writes `artifacts/registered_pulse.vcd` when that plusarg is present. Create `artifacts/diagnosis.json` containing exactly:

```json
{
  "schema_version": "1.0",
  "classification": "rtl" or "testbench-sampling-region",
  "first_divergence_time": integer VCD timestamp,
  "expected_valid": 0 or 1,
  "actual_valid": 0 or 1,
  "responsible_file": repository-relative path
}
```
