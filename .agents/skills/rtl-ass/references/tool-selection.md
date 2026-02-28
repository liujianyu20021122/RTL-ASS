# Verification tool selection and inventory

Use this reference only when the user requests executed verification, asks which tools RTL-ASS supports, or the selected/project-local verification flow cannot be used.

## Precedence and confirmation boundary

1. A user-selected tool or command flow has priority. Preserve it; do not replace it with an RTL-ASS adapter for convenience or structured JSON.
2. With no user selection, inspect the repository's documented build and verification entrypoints. Use an applicable project-local flow when it is usable and not forbidden.
3. RTL-ASS adapters are eligible only when verification is required and neither prior option applies. Ask the user to confirm both that no other local tool or flow should be used because it is unavailable or disallowed and that the named RTL-ASS fallback adapter may run. An explicit request for an RTL-ASS helper or backend is already a user-selected flow.

The fallback question must confirm the local-flow boundary and name the proposed evidence and backend, for example: “I found no selected or runnable project-local simulation flow. Please confirm that no other local tool or flow should be used and authorize RTL-ASS's Icarus Verilog adapter for the focused regression.” A generic request to edit RTL is not confirmation. If the user declines or cannot confirm, report `not_evaluated`; do not silently execute a fallback.

`rtl-ass doctor` is inventory and discovery only. It may be used to prepare an accurate fallback proposal, but it does not authorize or execute verification.

## Integrated fallback adapters

RTL-ASS does not install these executables. It discovers a locally installed executable only after the fallback is authorized.

| External executable | RTL-ASS operation | Evidence scope |
|---|---|---|
| Verilator | `verify lint`; `verify simulate --backend verilator` | lint/elaboration or compiled self-checking simulation |
| Icarus Verilog + `vvp` | `verify simulate --backend iverilog` | self-checking simulation |
| Yosys, with its ABC integration when mapping | `verify synth`; `verify formal --backend yosys`; `verify equiv --backend yosys` | generic/mapped synthesis, bounded SAT, or equivalence |
| SymbiYosys + Yosys + selected solver | `verify formal --backend sby` | bounded assertion checking with retained counterexample rules |
| EQY + compatible Yosys/SymbiYosys plugins + selected solver | `verify equiv --backend eqy` | equivalence with explicit reference/implementation identities |
| Z3, Boolector, Bitwuzla, CVC5, or Yices | selected by the SBY/EQY adapter | open-source formal solving; only the chosen solver is required |
| OpenSTA | `verify sta` | STA only with mapped netlist, exact Liberty, SDC, and constrained endpoints |
| GTKWave `fst2vcd` | `wave query` or `wave diff` on FST | bounded FST conversion and waveform query; VCD parsing itself is internal Python |

Manifest validation, verification-plan validation, evidence revalidation, SQLite/FTS5 retrieval, and lexical project inspection are internal deterministic operations. They do not execute the EDA tools above.

## Discovery-only inventory

The doctor may report Slang, Surelog, Verible, GTKWave's GUI, BWave, or OpenROAD. RTL-ASS currently has no evidence adapter for them. Discovery is not integration, and their presence must not be described as a supported RTL-ASS verification backend.

## Authorized fallback commands

After the selection boundary has been satisfied, use only the adapter needed for the requested claim. Representative forms are:

```bash
rtl-ass doctor
rtl-ass manifest validate compile.json
rtl-ass verify lint --manifest compile.json --artifact-dir artifacts/rtl-ass/lint
rtl-ass verify simulate --backend iverilog --manifest compile.json --artifact-dir artifacts/rtl-ass/simulation
rtl-ass verify synth --manifest compile.json --artifact-dir artifacts/rtl-ass/synthesis
rtl-ass verify formal --backend sby --manifest formal.json --depth 20 --solver z3 --artifact-dir artifacts/rtl-ass/formal
rtl-ass verify equiv --backend eqy --reference-manifest reference.json --implementation-manifest implementation.json --depth 1 --solver z3 --artifact-dir artifacts/rtl-ass/equivalence
rtl-ass verify sta --synthesis-evidence artifacts/rtl-ass/synthesis/<run>/run-evidence.json --liberty cells.lib --constraints design.sdc --top top --artifact-dir artifacts/rtl-ass/sta
```

Do not run every adapter as a checklist. Tool availability is not evidence, synthesis is not behavioral proof, and OpenSTA is not physical signoff.
