# Large-SoC effectiveness evaluation

This protocol tests whether RTL-ASS improves Codex on repository-scale RTL work and whether bounded knowledge retrieval adds an incremental benefit. It does not treat telemetry, corpus size, tool invocation, or a final explanation as proof of better RTL.

## Questions and contrasts

Evaluate the product and causal retrieval effects independently:

1. **Product effect:** native Codex versus the released retrieval-first RTL-ASS Skill with one to three relevant calibrated cards.
2. **Retrieval effect:** the same released Skill with an empty evaluation namespace, relevant calibrated cards, and plausible but irrelevant calibrated cards. A Skill-without-database condition is diagnostic only, not the primary product.

Do not combine these contrasts into one `off/on` headline. Workflow monitoring and the user-selected or project-local verification flow are identical in every condition; neither is a treatment. RTL-ASS EDA adapters remain disabled unless a separate preregistered case explicitly evaluates the user-confirmed fallback policy.

## Repository and task boundary

A repository-scale case uses a pinned, redistributable open-source revision with enough hierarchy and build metadata to exercise navigation and impact analysis. The task remains an issue-sized change with an independently gradable contract. Whole-chip compilation is not required merely to call a repository large.

Cover multiple architectures and at least these task classes across the campaign:

- build-boundary or generated-source attribution;
- cross-hierarchy integration and configuration/package semantics;
- ready/valid, bus, interrupt, or DMA behavior under backpressure;
- clock/reset-domain behavior with explicit synchronization scope;
- regression or waveform localization across more than one component;
- synthesis or STA only when the exact source closure, mapped netlist, Liberty, and constraints are available.

Start with bounded calibrated retrieval. Inspect the relevant subtree or declared build closure selected from the task and retrieved assumptions. Use `rtl-ass inspect <repository> --summary` only when task scope is genuinely unclear; the complete repository remains available to Codex, but an unbounded per-file inspection must not enter model context.

Pinned repository cases are materialized from a local Git object store; the agent remains offline. For example:

```bash
python3 evals/run_codex_ab.py \
  --output .rtl-ass/evals/core-v-mcu-event-irq \
  --replicates 1 --parallel 1 --timeout 900 --outer-bwrap \
  --soc-case soc-core-v-mcu-event-irq \
  --source-repository research/upstream/core-v-mcu
```

The materializer rejects a mismatched commit, tree, tracked-file count, affected source hash, injected-defect hash, hidden revision, hidden-test hash, or unsupported Git file mode. A one-pair development smoke is recorded in [the large-SoC smoke report](../evals/results/2026-09-03-large-soc-smoke.md); it is not a replicated effectiveness claim.

## Fixed experimental controls

Within each paired contrast, freeze and hash the repository revision, injected defect or task patch, prompt, protected files, grader, hidden tests, Skill/runtime, knowledge pack, model, reasoning effort, tool paths and versions, resource policy, and timeout. Run serially in alternating condition order. The agent workspace has no network and cannot read hidden graders or reference fixes.

Use at least five pairs per task for screening and more repetitions when paired outcomes remain unstable. Report task results per repository and task class; a heterogeneous aggregate is descriptive only.

## Independent grading

The grader, not Codex or RTL-ASS evidence, decides correctness. Prefer the upstream open-source test for the affected closure plus held-back tests and protected-file hashes. A passing compile is not functional success. A timeout can retain a correct partial candidate, but it remains a bounded task failure and is reported separately.

Report these outcome lanes independently:

- candidate correctness and regression escape;
- deliverable completeness and timely task success;
- current-candidate structured evidence and workflow compliance;
- elapsed time, input/output tokens, command failures, retries, peak memory, CPU/task pressure, and infrastructure exclusions;
- changed-file scope and unnecessary verification after a ready gate.

## Mechanism analysis

Pre-register the knowledge mechanism expected to matter for each case in a strict treatment manifest: exact task and card hashes, query concepts, eligible namespaces/statuses, a `relevant` or `plausible-irrelevant` label, applicability/non-applicability findings, and the coding or diagnosis decision the card could inform. Keep this manifest outside the agent workspace. Also observe preservation of the selected compile boundary, baseline reproduction, affected regression scope, and stopping, but do not count helper activity as Skill use. Trace correlation can explain an observed run, but it cannot by itself prove that an opaque reasoning step caused the outcome.

Each retrieval condition declares its required observable receipt and record-read boundary. Native Codex is still graded for correctness, delivery, safety, and evidence scope without being required to query an unavailable database. Tool fallback compliance is evaluated separately. A mechanism observed under an older audit policy is not retroactively relabeled—the historical finding and the policy change are recorded separately.

Do not claim a general Skill benefit unless correctness or bounded task success improves across more than one repository and task class without an unacceptable stability or resource regression. Evidence completeness is a separate product benefit, not a proxy for logic correctness.

## Knowledge retrieval ladder

Knowledge evaluation uses bounded cards rather than exposing a raw corpus dump:

1. empty namespace;
2. relevant reviewed cards derived from a different source revision or project;
3. plausible but irrelevant reviewed cards as a negative control.

Every card retains provenance, license, limitations, lifecycle state, and exact source hash. Hidden tests, task source, expected patches, reference implementations, and grader outputs are forbidden. Record the search receipt, returned IDs, full-content reads, and database hash before and after the run.

Measure retrieval quality as well as task outcome: relevant hit at the selected top-k, whether Codex inspected the hit, stale or incompatible assumptions, outcome delta, and token/latency delta. Retrieval occurrence and database size do not count as capability gains. Promote a reusable card only through the normal evidence and review gates after the evaluation corpus has been checked for contamination.
