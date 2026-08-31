# RTL-ASS 1.0

RTL-ASS is a vendor-neutral Codex skill for Verilog and SystemVerilog engineering. It augments Codex with RTL-specific task routing, deterministic open-source evidence adapters, bounded VCD/FST analysis, and an audited local knowledge index. Codex remains responsible for understanding the specification, editing code, interpreting evidence, and selecting the final implementation.

RTL-ASS does not call another model, generate RTL behind Codex's back, apply patches, or depend on proprietary EDA tools.

## 1.0 capabilities

- Verilog/SystemVerilog repository inspection without executing source.
- Verilator lint and Icarus Verilog self-checking simulation evidence.
- Yosys generic synthesis, bounded assertion checking, and combinational or bounded-sequential equivalence evidence.
- OpenSTA evidence only from an exact netlist, Liberty library, and SDC; unconstrained endpoints block closure claims.
- Bounded VCD queries and first-divergence analysis; resource-bounded FST conversion through `fst2vcd` with original and converted hashes.
- SQLite/FTS5 namespaces, immutable content identity, explicit RTL/TB/assertion roles, guarded lifecycle transitions, and append-only hash-chained audit events.
- Atomic verification/observation workflows, explicit failure attribution, candidate derivation, and portable license-aware knowledge packs.
- A first-party Apache-2.0 starter pack with RTL, TB, assertions, and focused engineering cards.

The core Python package uses only the standard library. EDA programs are optional open-source executables discovered at runtime.

## Install

Python 3.11 or 3.12 is supported.

```bash
python3 -m pip install rtl_ass-1.0.0-py3-none-any.whl
rtl-ass --version
rtl-ass doctor
```

Install the `rtl-ass` skill directory from the release archive into the Codex skills directory, or use the repository copy at `.agents/skills/rtl-ass/`. The helper launcher works from a source checkout or with the wheel installed. See [installation and removal](docs/installation.md) for complete commands.

## Quick start

```bash
# Inspect without executing RTL
rtl-ass inspect path/to/project --json

# Produce separate evidence classes
rtl-ass verify lint --source rtl/top.sv --top top --artifact-dir artifacts
rtl-ass verify simulate --source rtl/top.sv --source tb/top_tb.sv --top top_tb --artifact-dir artifacts
rtl-ass verify synth --source rtl/top.sv --top top --artifact-dir artifacts
rtl-ass verify formal --source rtl/top.sv --source formal/top_properties.sv \
  --top top_properties --depth 20 --initialization defined --artifact-dir artifacts

# Query only a bounded waveform window/signal cone
rtl-ass wave query artifacts/run.fst --signal 'tb.dut.*valid*' --start 100 --end 300 --max-events 200
rtl-ass wave diff artifacts/run.fst --expected tb.expected --actual tb.actual --start 100 --end 300

# Import and search the first-party starter pack
rtl-ass kb init --db .rtl-ass/knowledge.db --actor local-user
rtl-ass kb pack-validate library/starter/pack.json
rtl-ass kb import-pack library/starter/pack.json --db .rtl-ass/knowledge.db \
  --namespace builtin:starter --actor local-user
rtl-ass kb search ready --db .rtl-ass/knowledge.db --namespace builtin:starter
```

All commands return stable machine-readable JSON on success and structured JSON errors on failure. `doctor` reports discovery only; it never implies that verification ran.

## Trust model

Imported material starts `raw`; derived material starts `candidate`; neither is verified or promoted automatically. Verification requires exact passing evidence and is committed atomically with evidence records and links. Failed, blocked, timeout, and infrastructure outcomes are retained without being mislabeled as RTL defects. Pack import validates paths, byte bounds, content hashes, roles, relationships, and the pack identity before database writes.

The audit chain is tamper-evident rather than tamper-proof: a database owner can replace the whole database. See [audit model](docs/audit-model.md), [architecture](docs/architecture.md), and [knowledge packs](docs/knowledge-packs.md).

## Development and release verification

```bash
python3 -m compileall -q src tests evals tools .agents/skills/rtl-ass/scripts
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONOPTIMIZE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff format --check src tests .agents/skills/rtl-ass/scripts
ruff check src tests .agents/skills/rtl-ass/scripts
mypy src tools/release_audit.py tools/build_release_assets.py evals/validate_cases.py
python3 -m build
twine check dist/*
```

Evaluation scope and non-claims are documented in [evaluation](docs/evaluation.md). Release procedures are in [release process](docs/release.md). Contributions are governed by [CONTRIBUTING.md](CONTRIBUTING.md) and the root [AGENTS.md](AGENTS.md).

## License

Apache License 2.0. Upstream research checkouts remain quarantined and are not part of the distributed product.
