# Evaluation policy

## Measured effects and scope

RTL-ASS has shown modest efficiency improvements in specific retrieval examples and improved workflow completion
in the historical six-class audit. These are separate observations with different baselines, not a pooled score.

| Comparison | Measured result | Scope and tradeoff |
|---|---|---|
| Skill + empty versus Skill + relevant signed-width card | Aggregate elapsed time decreased 2.27%; both conditions passed 5/5 | Five pairs; relevant was faster in two, median paired time was 7.718 s slower, and input/output tokens increased 3.16%/2.63% |
| Skill + empty versus Skill + calibrated source file | Elapsed time decreased 8.61%, input tokens 21.75%, output tokens 9.10%; both candidates passed the frozen grader | One development pair; corrected-grader replay and final regression closure remain pending |
| Native Codex versus historical verification-oriented Skill | Task completion increased from 23/30 to 29/30; candidate correctness from 28/30 to 30/30 | Six transparent task classes; aggregate input tokens increased; predates the retrieval-first product |
| Native Codex versus Skill + relevant signed-width card | Strict-lint workflow compliance increased from 2/5 to 5/5; both conditions passed 5/5 | Elapsed time increased 28.04%; input/output tokens increased 74.64%/30.71% |

Sources: [frozen five-pair campaign](../evals/results/2026-09-05-frozen-causal-retrieval-campaign.md),
[source-file development observation](../evals/results/2026-09-05-file-application-smoke.md), and
[historical six-class audit](../evals/results/2026-09-01-codex-multitask-workflow-audit.md).
Use “modest, task-specific improvement” with its measured metric and baseline. Retain costs, failures, sample
counts, and audit status alongside benefits. Historical signed reports and machine-readable status fields retain
their original meanings. This editorial summary does not regrade a run or complete a pending acceptance gate.

## Evaluation dimensions

RTL-ASS separates four questions that are often incorrectly collapsed.

1. Retrieval correctness: namespace, lifecycle, provenance, receipt, contamination, and bounded-content tests.
2. Retrieval effectiveness: controlled empty/relevant/irrelevant-card comparisons plus native Codex, with the same model, prompt, selected verification flow, budget, and hidden acceptance tests.
3. Candidate RTL evidence: results from the user-selected or project-local flow, or from an explicitly confirmed RTL-ASS fallback, with exact identities and honest scope.
4. Optional adapter correctness: unit, schema, transaction, optimized-runtime, and real open-tool integration tests; adapter activity is not a model-effectiveness proxy.

The 1.0 release introduced the knowledge/evidence mechanisms and published the model-evaluation case manifest and protocol in `evals/`. The 1.1 release added the reviewed six-class audit: Codex loaded the isolated Skill, changed its verification behavior, and completed 29/30 tasks versus 23/30 without the Skill in those cases. Static keyword checks are not accepted as model evaluation.

The public cases cover specification-to-RTL, repair, RTL/TB attribution, waveform localization, SystemVerilog semantics, and timing-aware refinement. Hidden answers must remain outside any retrieval namespace available to the evaluated run. Record failed and blocked runs, model/version, token and elapsed budgets, commands, tool versions, candidate hashes, and all hidden-test results.

GK/KY scoring can audit an explicit candidate/report directory, but repository auto-discovery must not be used as a release score because quarantined upstream projects may be misidentified as candidates. A score is reported only with the exact candidate path, task contract, logs, run records, and gate effects.

## Capturing the internal workflow safely

Codex JSONL is treated as an observable execution trace, not permission to expose private chain-of-thought. The public/sanitized layer retains only lifecycle counts, hashed thread identifiers, redacted commands, file changes, final agent messages, token usage, tool evidence, and grader results. Reasoning content is skipped. Raw JSONL stays in an ignored local directory and is not a release artifact.

An activation claim requires a successful exact read of `.agents/skills/rtl-ass/SKILL.md` or its references, or successful execution of the repository helper path. Reading an unrelated global `SKILL.md`, a failed module probe, or a compound command whose unrelated final stage returns zero does not count. An evidence-closure claim requires current `run-evidence.json` records whose subject hashes include the final candidate and, where required, the unchanged supplied testbench. Correctness is decided independently by case-specific hidden graders, never by the agent's final statement or its own evidence.

Infrastructure failures remain visible and do not enter the valid denominator. A timeout under the declared budget is a valid task failure, even if the partial candidate later passes the external grader; report task completion and partial-candidate correctness separately. Diagnosis correctness, deliverable completeness, and task success are also separate fields. Report paired raw outcomes, evidence completeness, elapsed time, and token cost.

Workflow efficiency is reported independently. Strictly valid records with the same non-waveform `(kind, input_hash)` in different evidence files are redundant executions. After a successful `verify summarize --require-ready`, every later observable EDA command is post-ready activity. These findings never change candidate correctness, evidence validity, policy compliance, or infrastructure attribution.

For causal retrieval ablation, `--ablation retrieval` keeps RTL-ASS, the prompt, tools, model, effort, fixture, grader, and resource policy constant while changing an empty versus populated `eval:retrieval` namespace. For the primary product comparison, `--ablation product` compares native Codex against RTL-ASS with relevant calibrated knowledge. Both modes require `--retrieval-database <calibrated.db>` and `--retrieval-treatment-manifest <review.json>`; product mode rejects a plausible-irrelevant manifest. The database must contain one to three `verified` or `promoted` design/verification cards plus only their candidate tool-evidence records. The task-bound manifest remains outside the Codex workspace and binds exact prompt, public fixture, hidden grader, and card-content hashes, query concepts, decision targets, applicability/non-applicability findings, and the semantic contamination review. The runner rejects other namespaces, uncalibrated guidance, identity drift, direct public/private artifact hash matches, task-source paths, unknown license status, or cards without the semantic contamination-review marker. Reports retain both input hashes, retrieval receipts, returned identities, full-content reads, and any forbidden RTL-ASS EDA-adapter attempts. Workflow policy 1.4 requires a relevant treatment to include an observable full-content read. A reviewed plausible-irrelevant hit may be rejected from its receipt metadata without loading full content; returned, opened, and uninspected identities remain distinct so this relevance gate cannot be misreported as treatment exposure.

The first frozen executable result is documented in the [v1.3.0 retrieval ablation](../evals/results/2026-09-03-v1.3.0-retrieval-ablation.md). It used a raw imported pack under the historical policy and validates receipt/content-read instrumentation for one signed-width pair. Its scope is the historical raw-pack mechanism; the current product requires calibrated data.

The first strict treatment-bound development observations are documented in the
[causal retrieval control smokes](../evals/results/2026-09-04-causal-retrieval-controls.md). Their one completed
product pair and one plausible-irrelevant pair exposed launcher, applicability-routing, lint-policy, and shell
parsing defects. A later rerun was correctly stopped at the host-memory protection floor. These observations do
not meet the preregistered sample count.

The first two [calibrated retrieval-first development smokes](../evals/results/2026-09-04-calibrated-retrieval-smokes.md) retain both a strict-lint failure caused by incomplete application of a correct card and a later both-pass pair. They also document and correct command-normalization and empty-control audit defects. These development observations connect calibrated retrieval to candidate behavior and identify specific repairs for subsequent campaigns.

The [frozen five-pair causal retrieval campaign](../evals/results/2026-09-05-frozen-causal-retrieval-campaign.md)
completes the signed-width product, relevant, and plausible-irrelevant contrasts. All conditions reached 5/5
correctness. Relevant retrieval reduced aggregate elapsed time by 2.270%, with mixed paired timings and increased
tokens. Product and irrelevant-card elapsed time increased by 28.038% and 12.788%, respectively. The campaign also
records improved product strict-lint discipline and the policy 1.4 correction for bounded irrelevant-hit rejection.

Formal outer-isolation runs are globally serialized and resource-supervised with a cgroup CPU quota, memory/swap ceilings, process and total-runtime limits, a host-memory start gate, and continuously flushed telemetry. Failure to observe the cgroup or keep the monitor alive invalidates the run as infrastructure evidence. Continuous network errors have a separate 120-second stall limit. A resource or terminal transport failure is never scored as an RTL or model failure.

Each case declares required and allowed evidence classes. The trace monitor records case-extraneous evidence and observable attempts to use network/package acquisition, proprietary EDA, or another coding/model agent. It also detects off-condition Skill leakage, malformed trace lines, and protected-fixture edits. This policy audit remains separate from candidate correctness: it exposes workflow boundary violations without silently rewriting the grader result. Commands hidden inside an arbitrary generated program are outside this observable-trace claim.

The reviewed six-class result is in [`../evals/results/2026-09-01-codex-multitask-workflow-audit.md`](../evals/results/2026-09-01-codex-multitask-workflow-audit.md). Its measured completion gains apply to those cases. The public manifest's broader `effectiveness_status: not_evaluated` field remains unchanged and is separate from these observed results.

Repository-scale work uses the separate [large-SoC effectiveness protocol](soc-evaluation.md). It keeps workflow monitoring and the selected/project-local verification flow constant, measures calibrated retrieval as the primary treatment, and forbids treating raw corpus size or tool activity as an ability claim.

The first [large-SoC development smoke](../evals/results/2026-09-03-large-soc-smoke.md) found equal hidden-test correctness with materially higher Skill cost, while confirming bounded repository inspection and baseline-first repair. It also exposed a final-evidence retention defect. This pre-correction observation remains a recorded cost and evidence-retention regression; the later task-specific efficiency improvements do not reclassify it.
