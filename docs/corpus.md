# Corpus governance

The local corpus supplies attributable context to Codex; it does not train the model, replace RTL reasoning, or grant trust to imported code. Upstream source trees and the SQLite database are workstation-local and ignored by Git. The public repository distributes only policy and content hashes.

## Admission boundary

Every source in `corpus/upstream-sources.json` must have one explicit policy decision. Inclusion requires a clean pinned Git checkout, exact origin and full revision, no detected benchmark contamination, a tracked license file whose hash matches the reviewed finding, bounded UTF-8 HDL selections, and one isolated namespace. Unknown-license, benchmark-answer, generated-bulk, proprietary-flow, and intentionally broken collections remain excluded.

The current lock admits seven sources:

| Namespace | Source files | Intended use |
| --- | ---: | --- |
| `corpus:ibex` | 33 | raw production RTL/package context |
| `corpus:picorv32` | 11 | raw RTL and associated testbenches |
| `corpus:pulp-axi` | 93 | raw AXI RTL/package/testbench context |
| `corpus:rtl-skills` | 5 | raw verification templates |
| `corpus:sv-tests` | 1,028 | isolated language-conformance fixtures |
| `corpus:uvm-core` | 174 | raw UVM verification patterns |
| `corpus:verilog-axis` | 85 | raw AXI Stream RTL and testbenches |

Total: 1,429 locked Verilog/SystemVerilog files and 6,621,871 source bytes. The semantic lock identity is `73855d55370257469793d7504c1fc79c74eb20a481ba42bfedd6ea54c0963046`.

## Reproducible import

```bash
rtl-ass corpus lock corpus/ingestion-policy.json \
  --source-root research/upstream --output corpus/curated-lock.json
rtl-ass kb init --db .rtl-ass/index.db --actor corpus-review
rtl-ass kb import-corpus corpus/curated-lock.json \
  --source-root research/upstream --db .rtl-ass/index.db --actor corpus-review
rtl-ass kb stats --db .rtl-ass/index.db
```

Lock generation reads only tracked HDL selected by policy. Import rechecks repository identity, license identity, containment, raw byte count, and SHA-256 before constructing records. The entire batch and its audit events commit in one database transaction. Repeating an identical import creates no records or audit events; an immutable identity collision aborts the whole batch.

## Trust and refinement

Imported records are `raw` and carry `trust_status: quarantine`. Search source-specific namespaces deliberately; do not mix conformance fixtures into default design retrieval. Inspect exact source, assumptions, dependencies, license, and linked evidence before reuse.

Refinement creates a separate candidate with `kb derive`; it never rewrites upstream content. Verification attaches passing tool evidence for the candidate's exact content hash. Non-passing runs use `kb observe` with explicit target, testbench, specification, constraints, infrastructure, or unattributed attribution. Neither lock admission nor a successful standalone compile is sufficient for automatic promotion.

The local database is operational state, not a release asset. Public reusable packs must contain only deliberately distilled records whose redistribution terms and executable evidence have been reviewed.
