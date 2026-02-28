# File-level knowledge application evaluation

Receipt validity and a successful `kb show` command do not establish that a source file was used correctly.
The evaluator retains these historical observations and adds two independent checks:

1. `content_bound_read_ids` requires a successful visible show command with a complete JSON response whose
   source bytes hash to the returned record identity. Truncated, filtered, redirected, or unavailable output
   cannot receive this stronger credit. The sanitized trace stores identity/event position, not RTL text.
2. `knowledge_application` joins an agent declaration to an audited receipt, that content read, a current
   candidate file hash, reviewed applicability targets, and independently executed constraint checks.
   Overall task correctness cannot substitute for a missing constraint check.

The evaluation-only declaration is `artifacts/knowledge-use.json`, governed by
[`knowledge-use.schema.json`](../schemas/knowledge-use.schema.json) and the Python boundary validator.
Record IDs must be unique. Applied entries name the source hash, final target/hash, reason, and constraint IDs;
rejected entries have no target or applied constraints. An empty `uses` list means no declared use. Invalid
paths, symlinks, raw/candidate sources, stale identities, unread content, and unsupported constraints receive
no application credit. A recorded rejection is a declaration, not machine proof of correct rejection.

`supported_application` means an explicit use claim is consistent with those observable facts. It does not
prove that the model needed the reference, copied its implementation, or reasoned from it before editing.
Command/content observations are not introspection and can miss equivalent reads through other tools.
Run a separate paired empty/relevant contrast to measure benefit; preserve unsupported cases instead of
repairing their declarations after the run.

## First source-file case

`packet-tag-skid` implements a transformed packet stage under a registered handshake boundary. Five independently
reported constraints cover transformation/sidebands, stall stability, synchronous reset flush, registered
boundaries/skid capacity, and continuous throughput. Each runs at W/T = 1/1, 13/3 and 32/5. The hidden grader
requires completion markers, rejects unknown handshakes, and includes regression mutations for each constraint
and premature simulator termination. Strict DUT lint is a separate check.

The treatment uses the exact MIT-licensed `axis_register.v` hash pinned in
[`source.json`](../evals/retrieval_packs/axis-register/source.json), originally imported from the main corpus.
Its original verified gate covered lint/synthesis. New independent source calibration checks enabled sidebands,
stalls, reset flush and throughput in skid mode and rejects a simple-buffer mode that introduces bubbles.
The upstream component contains no packet-transform/tag-arithmetic task implementation. Its active-high reset
and optional sideband defaults require conscious adaptation. The contamination review is an auditable reviewer
assertion; hash-disjointness alone does not prove semantic independence.

Build an isolated evaluation database without changing the main corpus:

```bash
PYTHONPATH=src:. python3 evals/retrieval_packs/axis-register/calibrate_axis.py \
  --source-database .rtl-ass/index.db --output build/axis-calibration/axis.db
```

The command requires the exact pinned source record and project-local Icarus/vvp. It preserves source revision,
hash, MIT notice and main-database identity, executes behavioral calibration, and uses atomic `verify_record`
before exposing the isolated record. Outputs are an ignored database, `.artifacts/` evidence/source directory,
and `.treatment.json` case manifest. Existing outputs are never overwritten. Failure leaves diagnostic artifacts;
a retry uses a fresh output directory. No upstream source is added to the Git-tracked product.

Run one serialized, resource-supervised development pair:

```bash
PYTHONPATH=src python3 evals/run_codex_ab.py \
  --output build/axis-file-use-smoke --replicates 1 --parallel 1 --timeout 900 \
  --model gpt-5.6-sol --effort high --outer-bwrap \
  --skill-root build/formal-v1.3.0-extracted/rtl-ass \
  --case packet-tag-skid --ablation retrieval \
  --retrieval-database build/axis-calibration/axis.db \
  --retrieval-treatment-manifest build/axis-calibration/axis.treatment.json
```

Use the actual extracted Skill path. Both arms load the same Skill and direct project-local tools; only the
on arm receives the source record. Grader files and the treatment rationale stay outside the agent workspace.
Generated reports retain traces, candidate hashes, resource telemetry, returned/read identities, declarations,
constraint results and evidence hashes. Inspect individual outcomes before scheduling five fresh pairs.
One source file and one pair cannot establish correct use of the other 134 RTL files or general efficiency.
