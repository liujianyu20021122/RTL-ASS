# Frozen causal retrieval campaign

Date: 2026-09-05

This report records three five-pair `systemverilog-signed-width` campaigns against one extracted RTL-ASS 1.3
Skill payload. It separates the complete retrieval-first product, the contribution of one relevant card, and the
effect of one plausible-irrelevant lexical hit. The task has a strong native ceiling; these results do not establish
a general RTL capability or efficiency uplift.

Generated workspaces, raw traces, grader artifacts, telemetry, databases, and reports remain in ignored `build/`
directories. This tracked report contains only bounded aggregate results and independently rechecked identities.

## Frozen controls

- Model/runtime: `gpt-5.6-sol`, high reasoning, `codex-cli 0.152.1`.
- Execution: five independent serial pairs, 900-second per-run timeout, outer `bwrap`, capability drop, systemd
  cgroup supervision, 12 GiB start floor, and 8 GiB runtime host-memory floor.
- Case identity: prompt `d2981249223873e77171ce2c9fb0f0adcaf70789c5470005f2e8950e170fe1f3`, fixture
  `d81bd1ac3fa8e28575113c22b3ca540d21d8fd64b8aa91c7feb71b9f17c66977`, and hidden grader
  `341bf0b1838c4b99178efc8208a012b5c50788ef00fcbb36b647ba67a5a9404f`.
- Evaluated harness: `c1763546cbbb626da9cffddd680ac88009537e396d9afcff645722d0d7970bf2`.
- Extracted Skill tree: `9aedbaec52a2df9433b5b35e5debc92cb74abb7533da5f6f1600035475a20ca5`; embedded runtime:
  `cad3abec6530f95cd09f679c1afa51d70a7d9597053bec4ad924290a71c2f610`; combined on payload:
  `5a60281f916db495c31670f706016922fe5741942073ae6cb5ecd56f8c567b35`.
- Relevant database: `65a1aeb949d6657be334c8ae68c74ea245d11445c817f8e813bc100870145545`; plausible-irrelevant
  database: `38626ef5cee20fc472db4170f95d42d611c6468fcc52fc6ab7c917815d15027b`.
- RTL-ASS EDA adapters were forbidden. All 30 valid runs used the same direct project-local open-source tools; no
  run attempted an RTL-ASS EDA adapter.

`codex exec` does not expose a seed, so the pairs are independent replications rather than deterministic reruns.
The order alternated within pairs. Hidden grading independently required strict lint, visible and hidden
simulation, synthesis, and bounded sequential equivalence.

## Results

| Contrast | Condition | Correct / complete | Workflow compliant | Time (s) | Input / output tokens | Returned / opened cards |
|---|---|---:|---:|---:|---:|---:|
| Product | Native Codex | 5/5 | 2/5 | 1,991.201 | 2,543,150 / 73,312 | 0 / 0 |
| Product | Skill + relevant | 5/5 | 5/5 | 2,549.490 | 4,441,357 / 95,827 | 5 / 5 |
| Relevant retrieval | Skill + empty | 5/5 | 5/5 | 2,528.136 | 3,144,420 / 83,955 | 0 / 0 |
| Relevant retrieval | Skill + relevant | 5/5 | 5/5 | 2,470.751 | 3,243,671 / 86,161 | 5 / 5 |
| Irrelevant retrieval | Skill + empty | 5/5 | 5/5 | 2,115.524 | 3,106,014 / 84,413 | 0 / 0 |
| Irrelevant retrieval | Skill + plausible-irrelevant | 5/5 | 5/5 after policy 1.4 replay | 2,386.048 | 3,816,822 / 91,706 | 5 / 3 |

All three contrasts had five both-success pairs, no one-sided task success, no timeout, and no infrastructure
failure. A 5/5 success rate has a Wilson 95% interval of `[0.565518, 1.0]`; equal 5/5 outcomes cannot demonstrate
correctness uplift.

The product treatment added 28.038% total time, 74.640% input tokens, and 30.711% output tokens. It was faster and
used fewer input/output tokens in only one of five pairs. Its observable benefit was narrower: three native runs
used `-Wno-fatal` for required Verilator lint, while all five Skill-plus-relevant runs retained strict warning-clean
lint. The three directionally favorable workflow discordances have a two-sided exact sign-test value of 0.25, so
this is a task-local discipline signal, not a general claim.

Holding the Skill constant isolates the card. Relevant retrieval reduced aggregate time by 2.270%, but only two
of five treated runs were faster and the median paired difference was 7.718 seconds slower. It increased aggregate
input tokens by 3.156% and output tokens by 2.628%. Both sides were already 5/5 correct and workflow-compliant.
There is therefore no reliable efficiency or correctness benefit attributable to this card on this task.

Plausible-irrelevant retrieval added 12.788% total time, 22.885% input tokens, and 8.640% output tokens. Every
treated run used more input tokens, and only one was faster. Three runs opened the full card; two used the bounded
receipt summary to reject it because its scope covered opaque ready/valid payload transport rather than signed
arithmetic. No candidate incorporated the irrelevant rule, and correctness remained 5/5.

## Audit correction discovered by the campaign

The immutable irrelevant report used workflow policy 1.3, which incorrectly required every calibrated on-condition
hit to be opened. It consequently recorded pair 1 and pair 4 as noncompliant even though the Skill contract requires
full content only for selected hits and explicitly permits an inapplicable lexical hit to be rejected.

The shared evaluator now uses policy 1.4. A `relevant` treatment still requires at least one calibrated full-content
inspection. A `plausible-irrelevant` treatment may be rejected from its auditable receipt metadata, while returned,
opened, and uninspected identities remain separate metrics. If treatment metadata is absent, inspection remains
required. A read-only policy 1.4 replay left product at 2/5 versus 5/5 and relevant retrieval at 5/5 versus 5/5;
it corrected irrelevant retrieval to 5/5 versus 5/5 without altering correctness, artifacts, or the historical
report.

This is an evaluator abstraction repair, not a sample-specific exception. The complete workflow-audit module has
a regression for both relevant inspection and irrelevant rejection.

## Infrastructure exclusions

The first relevant campaign completed seven valid runs before `pair-04-off` entered repeated TLS
`unexpected-eof` reconnects. The transport monitor stopped only that cgroup after 120 seconds without progress.
The failed run lasted 485.128 seconds, had a 68,071,424-byte kernel memory peak, zero swap, and zero memory events.
Its candidate was independently correct and complete but remains excluded. Its sanitized-result SHA-256 is
`b6d3e320fc00aeae20a392240a9a753158f3a296c7d0db82b7463f1d60e8a7f2`.

The second attempt completed `pair-01-off`; `pair-01-on` then failed through the same terminal TLS path. It lasted
527.097 seconds, had a 67,567,616-byte kernel memory peak, zero swap, and zero memory events. Its correct and
complete candidate is also excluded. Its sanitized-result SHA-256 is
`8973c415eb96855fc9b6b156528164635fd2ce89eca8f031f9de1f4ea2bb79a0`.

Neither failure is evidence against RTL-ASS or Codex RTL ability. The third fresh campaign completed all ten runs.

## Integrity review

| Campaign | Embedded report hash | Report-file SHA-256 | Peak cgroup memory | Limit/OOM events |
|---|---|---|---:|---:|
| Product | `26fafbc21d4cc463494712f7acf99fcd17ecedc4e55b187851bb9609743bbe71` | `1e404e7d0ff260234d5d8ff9ab26c3b2d2b1f1ce260fc0e89df7a3f9c18a5563` | 84,434,944 B | 0 |
| Relevant | `afaeefd01ff835e73589e1856220f36ad2cc085d06cc119690046804460e32da` | `c74dde707ab51d94b3d41584cc09fe23786d1c3dc960bbe6debbef16aeaa997a` | 87,318,528 B | 0 |
| Irrelevant | `76ff969ddd4f707cab4a7548ac52744239aba57c70b0e7e021a200358828037f` | `8150eb43e13d220f4631a8369ca5effadb3d55fa8329e759299f5e38717d898a` | 86,290,432 B | 0 |

All embedded hashes were independently recomputed from canonical JSON. Across the three complete reports, 30 raw
traces, 30 sanitized stderr files, 30 telemetry files, 50 retrieval receipts, 30 final RTL subjects, 150 grader
evidence records, 690 raw grader artifacts, and 240 evidence subjects were rehashed with zero missing files and
zero mismatches. Both treatment databases retained their original hashes. All runs recorded zero cgroup swap and
zero memory-limit/OOM events.

A post-report local release rebuild is not falsely identified as the evaluated archive. Its Skill source members
are byte-identical to the campaign payload, and all 41 decompressed embedded-wheel members are byte-identical; the
wheel container differs because the rebuild normalized ZIP member timestamps to 1980-01-01 while the evaluated
wheel retained 2026-09-03 timestamps. This is logical-content equivalence, not artifact identity. The campaign
hashes above remain authoritative for the experiment, and publication must use the exact successful tag-CI assets.

## Decision and next work

The frozen campaign validates product isolation, calibrated receipt replay, relevant-card inspection, bounded
inapplicable-hit rejection, strict external grading, and the prohibition on RTL-ASS EDA adapters. It also shows why
the current comparison does not demonstrate database value: the visible defect is easy for native Codex, every
condition reaches 5/5 correctness, and the card restates a decision that Codex can derive directly.

Do not present this campaign as an RTL capability or efficiency uplift. The next effectiveness slice must:

1. use mutation-calibrated cards that resolve a non-obvious decision not directly exposed by the visible failure;
2. cover multiple task classes, including hierarchy/build-boundary, protocol/backpressure, reset/CDC, memory,
   assertion/formal, waveform localization, and synthesis/STA attribution where complete open inputs exist;
3. record `returned`, `selected`, `opened`, `applied`, and `rejected` as distinct structured retrieval states;
4. screen out tasks with a native 5/5 ceiling before spending the formal replication budget;
5. evaluate at least two pinned SoC repositories and four independently graded task classes under the M17
   protocol; and
6. optimize card length and retrieval/reference loading only after a task shows a correctness or decision-quality
   signal, because reducing overhead on a non-beneficial treatment is not a capability improvement.
