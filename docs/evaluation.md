# Evaluation policy

RTL-ASS separates three questions that are often incorrectly collapsed.

1. Helper correctness: unit, schema, transaction, optimized-runtime, and real open-tool integration tests.
2. Candidate RTL evidence: lint, simulation, waveform, formal, equivalence, synthesis, and STA artifacts with exact identities.
3. Model effectiveness: controlled Codex skill-off/skill-on trials using the same model, prompt, tool access, budget, seeds, and hidden acceptance tests.

The 1.0 release established the first two and published the model-evaluation case manifest and protocol in `evals/`. The 1.1 release adds the reviewed six-class audit, which demonstrates that Codex actually loads the isolated skill and changes its verification behavior while retaining the narrower conclusion that general RTL correctness uplift is not established. Static keyword checks are not accepted as model evaluation.

The public cases cover specification-to-RTL, repair, RTL/TB attribution, waveform localization, SystemVerilog semantics, and timing-aware refinement. Hidden answers must remain outside any retrieval namespace available to the evaluated run. Record failed and blocked runs, model/version, token and elapsed budgets, commands, tool versions, candidate hashes, and all hidden-test results.

GK/KY scoring can audit an explicit candidate/report directory, but repository auto-discovery must not be used as a release score because quarantined upstream projects may be misidentified as candidates. A score is reported only with the exact candidate path, task contract, logs, run records, and gate effects.

## Capturing the internal workflow safely

Codex JSONL is treated as an observable execution trace, not permission to expose private chain-of-thought. The public/sanitized layer retains only lifecycle counts, hashed thread identifiers, redacted commands, file changes, final agent messages, token usage, tool evidence, and grader results. Reasoning content is skipped. Raw JSONL stays in an ignored local directory and is not a release artifact.

An activation claim requires a successful exact read of `.agents/skills/rtl-ass/SKILL.md` or its references, or successful execution of the repository helper path. Reading an unrelated global `SKILL.md`, a failed module probe, or a compound command whose unrelated final stage returns zero does not count. An evidence-closure claim requires current `run-evidence.json` records whose subject hashes include the final candidate and, where required, the unchanged supplied testbench. Correctness is decided independently by case-specific hidden graders, never by the agent's final statement or its own evidence.

Infrastructure failures remain visible and do not enter the valid denominator. A timeout under the declared budget is a valid task failure, even if the partial candidate later passes the external grader; report task completion and partial-candidate correctness separately. Diagnosis correctness, deliverable completeness, and task success are also separate fields. Report paired raw outcomes, evidence completeness, elapsed time, and token cost.

Workflow efficiency is reported independently. Strictly valid records with the same non-waveform `(kind, input_hash)` in different evidence files are redundant executions. After a successful `verify summarize --require-ready`, every later observable EDA command is post-ready activity. These findings never change candidate correctness, evidence validity, policy compliance, or infrastructure attribution.

For retrieval ablation, `--ablation retrieval --retrieval-pack <pack.json>` keeps RTL-ASS, the prompt, tools, model, effort, fixture, grader, and resource policy constant while changing an empty versus populated `eval:retrieval` namespace. The runner rejects more than three records, direct public/private artifact hash matches, task-source paths, non-pattern roles, or records without the semantic contamination-review marker. Reports retain pack/tree hashes, exact retrieval receipts, returned record identities, and observed full-content reads. Automatic hash separation complements but does not replace the recorded human semantic review.

The first frozen executable result is documented in the [v1.3.0 retrieval ablation](../evals/results/2026-09-03-v1.3.0-retrieval-ablation.md). It validates the mechanism for one signed-width pair; it does not establish general retrieval uplift or expected overhead.

Formal outer-isolation runs are globally serialized and resource-supervised with a cgroup CPU quota, memory/swap ceilings, process and total-runtime limits, a host-memory start gate, and continuously flushed telemetry. Failure to observe the cgroup or keep the monitor alive invalidates the run as infrastructure evidence. Continuous network errors have a separate 120-second stall limit. A resource or terminal transport failure is never scored as an RTL or model failure.

Each case declares required and allowed evidence classes. The trace monitor records case-extraneous evidence and observable attempts to use network/package acquisition, proprietary EDA, or another coding/model agent. It also detects off-condition Skill leakage, malformed trace lines, and protected-fixture edits. This policy audit remains separate from candidate correctness: it exposes workflow boundary violations without silently rewriting the grader result. Commands hidden inside an arbitrary generated program are outside this observable-trace claim.

The reviewed six-class result is in [`../evals/results/2026-09-01-codex-multitask-workflow-audit.md`](../evals/results/2026-09-01-codex-multitask-workflow-audit.md). It validates the workflow mechanism but retains `effectiveness_status: not_evaluated` in the public case manifest for a general model-uplift claim.
