# Packet tag skid stage

Implement only `rtl/packet_tag_skid.sv`, top `packet_tag_skid`, in synthesizable SystemVerilog.
Parameters: `W=13`, `T=3`, and `parameter [W-1:0] MASK=1`. Support all positive W/T.
Ports: `clk`, active-low synchronous `rst_n`, `in_valid`, `in_ready`, `in_data[W-1:0]`,
`in_last`, `in_tag[T-1:0]`, `out_valid`, `out_ready`, `out_data[W-1:0]`, `out_last`, `out_tag[T-1:0]`.

- `transform`: for each accepted input, emit data XOR MASK, unchanged last, and tag plus one modulo 2**T.
- `stability`: preserve the entire transformed beat and valid until output acceptance; no loss, duplication or reordering under stalls.
- `reset`: a low rst_n sampled on a rising edge flushes all pending beats, including any skid storage. Do not require an asynchronous reset.
- `registered-boundary`: there must be no combinational path from out_ready to in_ready, or from input valid/data to output valid/data. Empty-stage latency is exactly one rising edge, with room to absorb one additional beat when downstream stalls.
- `throughput`: once primed, accept and emit one beat per cycle with both ends continuously ready/valid.

Use a standalone implementation; no unresolved upstream dependencies. If adapting substantial licensed source,
retain its copyright/license. No requirement to copy or instantiate any particular module.

The project-selected flow is direct Icarus (`iverilog -g2012`, `vvp`) plus strict Verilator lint on the DUT.
Create your own bounded self-checking tests under `artifacts/` and report executed commands. Preserve this spec.

For this workflow measurement only, write `artifacts/knowledge-use.json`, even if no records were used:
`{"schema_version":"1.0","uses":[]}`. For each consulted knowledge record (at most three), use exactly:
`record_id`, `content_hash`, `decision` (`applied` or `rejected`), `reason`, `target`, `target_hash`, `constraints`.
Applied uses name the final workspace-relative DUT file and its SHA-256; `constraints` contains only applicable
IDs from the five requirements above. Rejected uses have null target/hash and empty constraints.
Use exact identities from the retrieval receipt. Retrieve/show commands should emit complete JSON without
truncating or piping their output, so the observer can bind the source content hash. Do not fabricate a source
when no relevant record exists. A declaration is not verification evidence.
