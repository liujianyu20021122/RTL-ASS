# Causal retrieval treatment control smokes

Date: 2026-09-04

These development smokes exercise the new treatment-bound evaluator paths for the `systemverilog-signed-width`
case. They are single pairs, not effectiveness estimates. Generated databases, raw traces, workspaces, grader
artifacts, and telemetry remain in ignored `build/` directories.

## Inputs and controls

- Model/runtime: `gpt-5.6-sol`, medium reasoning, `codex-cli 0.152.1`.
- Execution: serial outer `bwrap`, capability drop, systemd cgroup supervision, and a 600-second per-run limit.
- Relevant treatment database: SHA-256
  `65a1aeb949d6657be334c8ae68c74ea245d11445c817f8e813bc100870145545`.
- Plausible-irrelevant treatment database: SHA-256
  `38626ef5cee20fc472db4170f95d42d611c6468fcc52fc6ab7c917815d15027b`.
- Each database has a valid seven-event append-only audit chain, one independently mutation-calibrated `verified`
  card, and one linked candidate tool-evidence record.
- Both treatment manifests bind the exact case prompt, public fixture, hidden grader, and card content. Codex did
  not see their relevance labels or review rationale.
- RTL-ASS EDA adapters were forbidden. Both conditions retained the direct open-source project flow.

## Completed observations

| Contrast | Condition | Result | Time (s) | Input / output tokens | Calibrated records returned / inspected |
|---|---|---:|---:|---:|---:|
| Product | native Codex | pass | 291.044 | 333,414 / 9,407 | 0 / 0 |
| Product | Skill + relevant card | pass | 321.368 | 419,480 / 10,759 | 1 / 1 |
| Irrelevant control | Skill + empty index | pass | 409.060 | 495,887 / 13,764 | 0 / 0 |
| Irrelevant control | Skill + plausible-irrelevant card | fail: strict lint | 550.069 | 825,411 / 15,217 | 1 / 1 |

The completed product pair proves that native Codex can be kept free of both Skill and database while the treated
condition activates the exact Skill, replays a calibrated receipt, reads the selected card, leaves the database
unchanged, and produces a correct candidate without using RTL-ASS EDA adapters. The treated run cost 30.324
seconds (+10.419%), 86,066 input tokens (+25.814%), and 1,352 output tokens (+14.372%) more in this one sample.
Equal correctness and one sample prohibit either a quality-uplift or expected-overhead claim.

In the irrelevant control, Codex explicitly stated that the ready/valid payload card did not apply to signed
arithmetic and did not use its rule as a patch. It nevertheless widened only the sum and left the saturation
thresholds narrower. Its own lint command demoted two `WIDTHEXPAND` warnings and described them as expected;
the independent strict grader rejected those warnings. Visible and hidden simulation, synthesis, and bounded
equivalence still passed. This is association evidence for a routing/signoff failure, not proof that the irrelevant
card caused the failure: the paired runs are independent because `codex exec` exposes no seed.

The product report has embedded hash
`9733e72d2ff2d35cb35b725f42849ff22f52d887a9eb98be25ba4d0d943c16ea` and report-file SHA-256
`147a041e110b7869965ea102885e44034da6e3afcdcbbade9c3b52dea9d8e63c`. The irrelevant-control report has
embedded hash `e1c7793675fd588b19265f25ab4b755d222a4cedef1de140bdb68010032a9b27` and report-file SHA-256
`ffb3fa8819dd714df3809ab17d20832443fb9e7c8526ed3c3e3595b22da8d9ae`.

## Defects found and forward repairs

1. The first product-on trace tried a bare `rtl-ass` executable and received exit 127 before recovering through
   the source module. The Skill now directs Codex to the hash-verifying launcher adjacent to `SKILL.md`; policy
   1.1 records a failed bare entrypoint as an efficiency finding. Replaying the immutable trace finds exactly one.
2. An inapplicable lexical hit could suppress the material conditional RTL reference. The Skill now requires an
   explicit applicable/partial/inapplicable classification and says that an inapplicable hit is a no-relevant-result
   outcome, not a replacement for the governing reference.
3. Warning-demotion flags could turn unresolved lint findings into an apparent local pass. Skill guidance and the
   shared evaluation rules now require resolution or an explicit repository waiver. Workflow policy 1.3 records
   `-Wno-fatal` and `--Wno-fatal` on required Verilator lint as violations.
4. The command parser treated an unquoted shell newline as whitespace, allowing a tool after `set -o pipefail` to
   evade the new policy. The shared parser now treats unquoted newlines as command separators. Regression tests
   cover both warning-flag spellings and the multiline form.

The signed historical reports remain immutable under their original policy. Forward replay marks all four runs as
noncompliant for warning demotion and additionally marks the product-on run inefficient for its missing bare
entrypoint. Correctness and infrastructure attribution are unchanged.

## Resource-protection stop

A post-repair product rerun stopped after its native condition when host available memory crossed the configured
8 GiB floor. The candidate independently passed strict lint, visible and hidden simulation, synthesis, and
equivalence, but the run is an infrastructure exclusion and no paired report exists. Its cgroup peaked at only
69,414,912 bytes and 68 tasks, used no swap, and recorded zero cgroup memory events. Read-only host inspection
showed unrelated pre-existing Vivado processes consuming the dominant memory; RTL-ASS neither invoked nor
terminated them. The supervisor killed only its own cgroup and prevented an unsafe second condition. The retained
sanitized result SHA-256 is `47c873422bd40a72a100e681361283366cad331b196c003e25769cc90b64b6ba`.
The existing start preflight had required at least 12 GiB available (the 8 GiB host floor plus the 4 GiB per-scope
maximum) and passed; the unrelated host load increased after launch, so no missing-preflight defect was inferred.

## Completed post-repair product smoke

After host available memory recovered above the unchanged 12 GiB start threshold, a fresh source-tree development
pair completed under the repaired Skill and policy 1.3. Both candidates passed independent strict lint, visible and
hidden simulation, synthesis, and bounded equivalence. Native Codex nevertheless used `-Wno-fatal` in one required
lint command, so its candidate was correct and complete but its observable workflow was noncompliant. The treated
condition used warning-clean `--Wall` lint, returned and inspected the one calibrated relevant card through two
valid receipts, left the database unchanged, and was workflow-compliant. Neither condition invoked an RTL-ASS EDA
adapter.

| Condition | Candidate / workflow | Time (s) | Input / output tokens | Observable commands |
|---|---|---:|---:|---:|
| Native Codex | correct / noncompliant | 250.103 | 243,219 / 8,656 | 8 |
| Skill + relevant card | correct / compliant | 411.725 | 659,817 / 14,525 | 28 |

The treated condition cost 161.622 seconds (+64.622%), 416,598 input tokens (+171.285%), and 5,869 output tokens
(+67.803%) more. Its process improvement is narrow but observable: it reproduced the baseline before editing and
did not demote required lint findings. The card's signed-width rule was applicable and correctly reflected in the
patch, but native Codex independently found the same root cause, so this pair supplies no correctness-uplift
evidence. Observable extra work included loading four task-relevant reference files, retrieval bookkeeping, one
corrected formal-harness attempt, and individually repeated width configurations. The Skill's progressive router
was followed: the four references covered governance, RTL semantics, verification, and the required formal claim,
so this trace does not justify deleting a reference as “irrelevant.” It does justify measuring whether batched
parameter checks reduce command and context churn, but one independent pair cannot estimate that effect.

The completed report has embedded hash
`f6e2c9017afa7e6feb52f54f744ea9da5ff907983dd7cdfd0acd9aaea08c005c` and report-file SHA-256
`a8ade35c5bfbbda0470943ad9987b2ef8bc6ff0db172d6d488f9e8e864495088`. Independent replay reproduced the
embedded hash and every retained trace, stderr, and telemetry hash. The relevant database remained at SHA-256
`65a1aeb949d6657be334c8ae68c74ea245d11445c817f8e813bc100870145545`. Cgroup memory peaks were
108,642,304 bytes off and 82,874,368 bytes on; peak tasks were 62 and 69, with zero swap and zero memory events.

## Decision

The fresh post-repair product pair is complete and validates the corrected workflow policy, retrieval receipt, and
resource supervision. It also confirms that the current treatment still has substantial single-sample overhead.
Do not extrapolate correctness or efficiency from these development pairs. Before estimating uplift or expected
overhead, freeze an extracted release payload and run at least five new serial pairs for product, relevant
retrieval, and plausible-irrelevant retrieval. Keep the existing 12 GiB start threshold and 8 GiB runtime floor.
