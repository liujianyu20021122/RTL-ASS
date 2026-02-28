# RTL-ASS 1.3

RTL-ASS is a retrieval-first, vendor-neutral Codex skill for Verilog and SystemVerilog engineering. It gives Codex bounded access to calibrated, provenance-bearing RTL design, testbench, assertion, and bug-pattern knowledge. Codex remains responsible for understanding the specification, editing code, reasoning about applicability, interpreting evidence, and selecting the final implementation.

RTL-ASS does not call another model, generate RTL behind Codex's back, apply patches, or replace a user-selected or project-local verification flow. Its open-source EDA adapters are optional fallbacks and are never the primary Skill mechanism.

## 1.3 capabilities

- Retrieval-first use of explicit SQLite/FTS5 namespaces, immutable receipts, calibrated lifecycle state, provenance, license metadata, RTL/TB/assertion roles, and negative evidence.
- Verilog/SystemVerilog repository inspection without executing source.
- One versioned CompileManifest for ordered sources, library files, include directories, language mode, defines, parameters, and top across every source-based adapter.
- Optional, explicitly selected or confirmed fallbacks for Verilator lint/simulation and Icarus Verilog self-checking simulation evidence.
- Optional, explicitly selected or confirmed Yosys synthesis/bounded SAT, SymbiYosys assertion, and EQY equivalence fallbacks with explicit solver, depth, initialization, and counterexample semantics.
- Optional, explicitly selected or confirmed OpenSTA evidence only from an exact netlist, Liberty library, and SDC; unconstrained endpoints block closure claims.
- Bounded VCD queries and first-divergence analysis; optional confirmed FST conversion through `fst2vcd` with original and converted hashes.
- Atomic verification/observation workflows, explicit failure attribution, candidate derivation, and portable license-aware knowledge packs.
- A first-party Apache-2.0 starter pack with RTL, TB, assertions, and focused engineering cards.
- A reviewed 1,429-file open-source HDL corpus lock with isolated provenance and lifecycle state; upstream code is not redistributed.
- A six-class paired Codex workflow audit covering RTL generation, repair, RTL/TB attribution, SystemVerilog signed arithmetic, FST localization, and OpenSTA-driven refinement.
- Task-scoped verification plans, current-evidence summaries, duplicate-run detection, and one bounded EDA execution lock per workspace.
- Immutable retrieval receipts plus task-bound relevant/plausible-irrelevant treatment manifests and separate native-product or empty-index causal comparisons.

The core Python package uses only the standard library. EDA programs are optional open-source executables discovered at runtime.

## Install

Python 3.11 or 3.12 is supported.

```bash
python3 -m pip install rtl_ass-1.3.0-py3-none-any.whl
rtl-ass --version
rtl-ass doctor
```

Install the complete `rtl-ass` skill directory from the release archive into the Codex skills directory, or use the repository copy at `.agents/skills/rtl-ass/`. The release Skill carries a hash-verified embedded runtime; the repository launcher uses the matching source tree. See [installation and removal](docs/installation.md) for complete commands.

## Knowledge-first quick start

Ordinary Skill use starts from an existing audited database. Search `promoted` records first, then `verified` records when no relevant promoted card exists. Do not use raw corpus files as default coding guidance.

```bash
# Inspect the audited inventory and explicit namespaces
rtl-ass kb stats --db .rtl-ass/index.db

# Retrieve no more than three calibrated references and retain the receipt
rtl-ass kb search 'ready valid backpressure' --db .rtl-ass/index.db \
  --namespace builtin:starter --status verified --match any --limit 3 \
  --actor codex --output artifacts/rtl-ass/retrieval.json
rtl-ass kb show <record-id> --db .rtl-ass/index.db --include-content

# Inspect without executing RTL
rtl-ass inspect path/to/project --summary
```

Database initialization, import, derivation, verification, and promotion are explicit curation operations, not side effects of a coding request. See [knowledge packs](docs/knowledge-packs.md) and [corpus governance](docs/corpus.md).

## Optional verification fallback

Verification precedence is: the user's selected flow, then an applicable documented project-local flow, then an RTL-ASS fallback. When neither prior flow is usable or permitted and executed verification is required, Codex must ask the user to confirm both that no other local flow should be used because it is unavailable or disallowed and that the named RTL-ASS backend may run. An explicit request for that helper/backend is already a user-selected flow. The complete integrated and discovery-only inventory is in [tool selection](.agents/skills/rtl-ass/references/tool-selection.md).

After that boundary is satisfied, representative commands are:

```bash
# Inventory only; this does not authorize or execute verification
rtl-ass doctor

# Validate Codex's explicit final-claim plan
rtl-ass verify plan verification-plan.json

# Produce separate evidence classes
rtl-ass verify lint --source rtl/top.sv --top top --artifact-dir artifacts
rtl-ass verify simulate --source rtl/top.sv --source tb/top_tb.sv --top top_tb --artifact-dir artifacts
rtl-ass verify simulate --backend verilator --manifest compile.json --artifact-dir artifacts/verilator
rtl-ass verify synth --source rtl/top.sv --top top --artifact-dir artifacts
rtl-ass verify synth --source rtl/top.sv --top top --liberty lib/cells.lib \
  --artifact-dir artifacts/mapped-synthesis
rtl-ass verify sta --synthesis-evidence artifacts/mapped-synthesis/synthesis-yosys-*/run-evidence.json \
  --liberty lib/cells.lib --constraints constraints/top.sdc --top top --artifact-dir artifacts/sta
rtl-ass verify formal --source rtl/top.sv --source formal/top_properties.sv \
  --top top_properties --depth 20 --initialization defined --artifact-dir artifacts
rtl-ass verify formal --backend sby --manifest formal-compile.json \
  --depth 20 --initialization defined --solver z3 --artifact-dir artifacts/sby
rtl-ass verify equiv --backend eqy --reference-manifest reference.json \
  --implementation-manifest implementation.json --depth 1 --solver z3 --artifact-dir artifacts/eqy

# Recheck current evidence and stop when every required claim is satisfied
rtl-ass verify summarize --plan verification-plan.json \
  --evidence regression=artifacts/simulation/<run>/run-evidence.json --require-ready

# Query only a bounded waveform window/signal cone
rtl-ass wave query artifacts/run.fst --signal 'tb.dut.*valid*' --start 100 --end 300 --max-events 200
rtl-ass wave diff artifacts/run.fst --expected tb.expected --actual tb.actual --start 100 --end 300

```

All commands return stable machine-readable JSON on success and structured JSON errors on failure. `doctor` reports discovery only; it never implies that verification ran.

## Trust model

Imported material starts `raw`; derived material starts `candidate`; neither is verified or promoted automatically. Verification requires exact passing evidence and is committed atomically with evidence records and links. Failed, blocked, timeout, and infrastructure outcomes are retained without being mislabeled as RTL defects. Pack import validates paths, byte bounds, content hashes, roles, relationships, and the pack identity before database writes.

The audit chain is tamper-evident rather than tamper-proof: a database owner can replace the whole database. The reviewed corpus lock describes 1,429 raw Verilog/SystemVerilog files across seven isolated namespaces without redistributing their code; those raw files are inventory, not calibrated recommendations. See [audit model](docs/audit-model.md), [architecture](docs/architecture.md), [corpus governance](docs/corpus.md), and [knowledge packs](docs/knowledge-packs.md).

## Development and release verification

```bash
python3 -m compileall -q src tests evals tools .agents/skills/rtl-ass/scripts
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONOPTIMIZE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff format --check src tests evals tools .agents/skills/rtl-ass/scripts
ruff check src tests evals tools .agents/skills/rtl-ass/scripts
mypy src tests tools evals
python3 -m build
twine check dist/*.whl dist/*.tar.gz
```

Evaluation scope and non-claims are documented in [evaluation](docs/evaluation.md). Reviewed results include the [six-class Codex workflow audit](evals/results/2026-09-01-codex-multitask-workflow-audit.md), the historical raw-pack [v1.3.0 retrieval instrumentation ablation](evals/results/2026-09-03-v1.3.0-retrieval-ablation.md), and the first [calibrated retrieval-first development smokes](evals/results/2026-09-04-calibrated-retrieval-smokes.md). The calibrated smokes validate the corrected mechanism and retain one partial-application failure, but their one-pair samples do not establish general uplift or expected overhead. See the [v1.3.0 release notes](docs/releases/v1.3.0.md) and [release process](docs/release.md). Contributions are governed by [CONTRIBUTING.md](CONTRIBUTING.md) and the root [AGENTS.md](AGENTS.md).

## License

Apache License 2.0. Upstream research checkouts remain quarantined and are not part of the distributed product.
