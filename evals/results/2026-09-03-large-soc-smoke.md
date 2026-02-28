# RTL-ASS large-SoC development smoke — 2026-09-03

This is a one-pair development smoke, not an effectiveness result. It exercised a complete pinned CORE-V-MCU repository context while grading one issue-sized SoC event-generator repair. The run identified useful workflow differences and two Skill/evaluator defects that were corrected only after the frozen run; a fresh replicated campaign is required before any uplift claim.

## Frozen boundary

- Source: `openhwgroup/core-v-mcu` commit `cf5be30bb048ab51d7f699296c0db702399f243a`, tree `a10e2f3af734726d02f1e3e3df28689576c84a59`, 1,414 tracked files.
- Injected defect: one content-bound change in `rtl/core-v-mcu/soc/soc_event_generator.sv`; affected input hash `df46afdb674b905030e1b0772b55caf36eb544b436bf3ac425d61658c3a4392a`, mutated hash `6517dd158bd76f15713a66547372e1e447badcb33039edc5b24454b4528c6fe4`.
- Hidden regression: upstream test from commit `3a0d194c0030bae3aa3a119fc08b06b2a6d80509`, hash `308668985b71bdca21fd7708574339206f97a19f0655767ff84146a3f9af872c`; it was not mounted into either Codex workspace.
- Codex: `codex-cli 0.152.1`, `gpt-5.6-sol`, high reasoning, 900-second per-run timeout, serial outer isolation and identical cgroup policy.
- Report identity: embedded report hash `964c3eaf8888f431f2943c5f1379e72b3e27d5b63e11ff5632da2872b2e9f504`; local report-file SHA-256 `462c252bd7b1f3c93c249ea3027a91d2fb6695a35b6eb411207a4a446fd39881`.

The public materializer validates the full commit, tree, file count, affected source hash, mutation post-hash, hidden revision, hidden-test hash, and per-artifact license finding before constructing a new fixture. The raw trace, private materialization, and bulky workspaces remain in ignored local storage.

## Outcome lanes

| Condition | Hidden correctness | Timely task | Duration | Input tokens | Output tokens | Kernel memory peak |
|---|---:|---:|---:|---:|---:|---:|
| Native Codex | 1/1 | 1/1 | 241.470 s | 836,558 | 9,607 | 82,624,512 B |
| RTL-ASS, retrieval disabled | 1/1 | 1/1 | 439.037 s | 2,758,164 | 18,115 | 88,145,920 B |

Both conditions made the same minimal one-file repair and passed the independent Icarus regression. Both inherited the pinned upstream closure's Verilator warnings, so lint was reported but deliberately not used as the functional correctness gate. Neither condition timed out or encountered resource, swap, monitor, or transport failure.

The Skill condition was 81.82% slower, used 229.70% more input tokens, and used 88.56% more output tokens in this pair. One sample cannot estimate expected overhead, but it rules out describing this run as an efficiency win.

## Observable workflow

Replaying the immutable raw trace with tracked-file ordering shows:

- Native Codex edited the affected RTL before executing a behavioral check, then created and ran a focused testbench.
- RTL-ASS first executed bounded `inspect --summary`, built a source manifest and testbench, reproduced the unrelated-IRQ failure, and only then edited the tracked RTL.
- RTL-ASS validated one compile boundary and one verification plan and stopped EDA work after a successful ready gate.
- It also made three failed helper calls while learning that CompileManifest paths cannot escape upward from a deep artifact directory. This is a documented safety invariant, but the Skill did not explain placement sharply enough.

These observations support a mechanism hypothesis: the Skill can impose bounded repository discovery, failure-first repair, one compile identity, and explicit stopping. They do not show that those mechanisms caused a correctness improvement here, because both candidates were correct.

## Defects found

1. The original workflow monitor treated any newly generated artifact as the first file change. It now reports the first change to a file present in the frozen input separately, so creating a testbench cannot be mistaken for editing product RTL.
2. The Skill condition removed its root-level CompileManifest after `verify summarize` had passed. The final simulation was real and passed, but the evaluator correctly rejected the now-unverifiable evidence dependency; complete current structured evidence was therefore 0/1. The Skill now requires all final evidence inputs, including a root-level manifest, to remain at their hashed paths through delivery.

Because both fixes postdate this run, the smoke is retained as negative process evidence. It must not be silently reinterpreted as if the corrected Skill or monitor produced it.

## Knowledge conclusion

This smoke disabled retrieval and says nothing about database uplift. The current local database contains 1,440 records and 6,640,894 unique source bytes, but 1,432 records are `raw`, only two are `verified`, and none are `promoted`. The two verified records passed lint and synthesis gates only. Raw corpus size is therefore inventory, not demonstrated RTL ability.

The existing one-pair signed-width retrieval ablation had equal correctness in empty and relevant-card conditions while the relevant-card run cost more time and tokens. The retrieval mechanism is real; incremental RTL-quality uplift remains `not_evaluated`. The next confirmatory test must keep the Skill fixed and compare empty, pre-reviewed relevant, and plausible-irrelevant namespaces across multiple tasks without deriving cards from the target or hidden grader.

## Corrected-rule replay — 2026-09-04

A second frozen one-pair development replay tested the evidence-retention instruction added after the first smoke. It used the same source commit, tree, mutation, hidden regression, model, reasoning effort, timeout, and resource policy. The historical report remains under `.rtl-ass/evals/2026-09-03-soc-core-v-mcu-event-irq-skill-smoke2`; embedded report hash is `5b924ec1b5ad26a41103496340a788da5f7679e1f9f70ad4234562933dff4750`, and the sanitized report-file SHA-256 is `767867753195b0b35d221ccef0926cfd720f70e74b0c430f4e9d9e26d412b6ea`.

| Condition | Hidden correctness | Timely task | Structured evidence | Duration | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|
| Native Codex | 1/1 | 1/1 | 0/1 | 297.756 s | 898,331 | 9,098 |
| RTL-ASS, retrieval disabled | 1/1 | 1/1 | 1/1 | 415.572 s | 2,065,916 | 16,006 |

The Skill run retained valid current-candidate lint and simulation records through delivery, so the evidence-retention defect moved from 0/1 to 1/1 in this replay. It again used a bounded project summary and reproduced the behavioral failure before changing tracked RTL, with no post-ready EDA call, timeout, transport failure, resource event, or exact retry. Relative to native it was 39.57% slower, used 129.97% more input tokens, and used 75.93% more output tokens. Both candidates had the same minimal repaired RTL hash.

The replay also exposed a distinct audit gap. The Skill used repeated inline source/define/parameter descriptions for simulation and lint instead of validating one CompileManifest, despite the complex multi-source, multi-backend closure. Audit policy 1.0 marked the run compliant because the case had no executable mechanism requirements. Policy 1.1 then added declarative Skill-required mechanisms; this SoC case temporarily required bounded summary before tracked edits, baseline evidence before tracked edits, and manifest validation before evidence. Under that historical policy the retained Skill run would be noncompliant for the missing manifest mechanism. The original signed report is not rewritten or reclassified.

The later retrieval-first product correction supersedes manifest or RTL-ASS adapter use as a required SoC Skill mechanism. Future primary comparisons keep the user-selected or project-local verification flow fixed and grade calibrated retrieval separately; CompileManifest is required only when an RTL-ASS execution adapter has been explicitly selected or confirmed as fallback. This note changes the future protocol, not either historical report or its policy-version result.
