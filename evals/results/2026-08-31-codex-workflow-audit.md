# Codex RTL-ASS workflow audit — 2026-08-31

## Scope

This is a transparent, single-task workflow audit, not a benchmark or a general model-uplift result. It used `codex-cli 0.148.0`, `gpt-5.6-sol`, medium reasoning, one identical FIFO-repair prompt, isolated per-run Codex homes, and external Verilator/Icarus/Yosys grading. The published hidden testbench was excluded from each Codex workspace but is not secret after publication.

The host rejected Codex's nested `workspace-write` sandbox (`bwrap: ... RTM_NEWADDR`), so the counted runs used `danger-full-access` inside disposable evaluation Git workspaces. This weakens OS-level isolation and is a disclosed limitation.

## Observable workflow

The completed skill-on trace shows this sequence:

1. exact read of `.agents/skills/rtl-ass/SKILL.md`;
2. selective read of task-routing, RTL design, and verification guidance;
3. baseline self-checking simulation and failure inspection;
4. minimal RTL pointer-wrap repair without changing the supplied testbench;
5. normalized lint, simulation, and synthesis runs whose passing `run-evidence.json` records bind the final RTL hash and, for simulation, the unchanged testbench hash;
6. supplemental bounded formal work with its scope and non-passing attempts retained;
7. external hidden lint/simulation/synthesis grading.

The sanitizer retains event counts, redacted commands, file changes, final agent messages, usage, evidence metadata, and grader output. It hashes thread identifiers and omits reasoning item content.

## Five-pair finding before the stop-rule correction

- Prompt hash: `5e41153218b094527b504cdc8e980dae0c5c71092498a7805a2b5a90f9257319`
- Fixture hash: `e5a2202bff52742e2fa377c03104f46dc0d23d0d6a2f797a88d882abf7d24490`
- Hidden grader hash: `96110fc7b5320c23900ffbf84eae6b40b50a65831bbeb1e0226f5d3dca2a283c`
- Reviewed local report hash: `595c41f8f2442879f35acc4375d1e309f71fbc117fee8731c1b55cb728831428`

| Condition | Runs | Candidate passed external grader | Completed within 600 s | Complete bound lint/sim/synth evidence | Timeouts |
|---|---:|---:|---:|---:|---:|
| Skill off | 5 | 5 | 5 | 0 | 0 |
| Skill on | 5 | 5 | 1 | 5 | 4 |

All four skill-on timeouts occurred after the candidate and minimum evidence closure were already correct. Their workspaces contained repeated supplemental formal runs: between two and twelve `formal` records per run, including blocked, failed, and passing attempts. This demonstrated a real evidence mechanism but an unacceptable stopping-policy failure.

The timeout decoder also discarded partial JSONL in those four runs because `TimeoutExpired.stdout` arrived as bytes. Their normalized evidence and external grades remain usable, but exact skill-read/command capture does not. The decoder now preserves partial byte output. Aggregate skill-on token totals from this batch are incomplete and must not be compared with skill-off totals.

## Forward check after the correction

The skill now requires lowest-cost sufficient evidence, selective reference loading, and a stopping rule for supplemental formal/equivalence/waveform/STA work. A fresh pair used the corrected skill and trace decoder.

Report hash: `574db311ec0957f0d23d065cb817ba7f241bdb126b20dca0668887e0abc67dbe`

| Condition | Task success | External grade | Bound structured evidence | Duration | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|
| Skill off | 1/1 | pass | no | 303.0 s | 144,992 | 3,984 |
| Skill on | 1/1 | pass | yes | 534.6 s | 714,080 | 9,891 |

The skill-on run made one supplemental formal attempt, inspected the counterexample, made one justified harness correction, then obtained a bounded pass and stopped. It no longer exhausted the 600-second budget, but it still used about 1.76 times the elapsed time and 4.93 times the input tokens of the paired off run.

## Decision

- Skill activation is real and observable in a completed trace; it is not inferred from the final prose.
- The normalized evidence mechanism is real: final lint, simulation, and synthesis evidence binds the exact repaired candidate, and the external grader independently confirms it.
- General RTL correctness uplift is not established. The task has a ceiling effect because skill-off Codex also produced correct candidates in all five runs.
- The original skill-on stopping behavior was ineffective under the declared budget. The correction passed one forward check, but efficiency remains materially worse and needs evaluation across more task classes.
- Project-level model effectiveness therefore remains `not_evaluated`. Future claims require diverse generation, debug, RTL/TB attribution, waveform, formal, and timing tasks with independent hidden graders and more paired replications.
