# Evaluation policy

RTL-ASS separates three questions that are often incorrectly collapsed.

1. Helper correctness: unit, schema, transaction, optimized-runtime, and real open-tool integration tests.
2. Candidate RTL evidence: lint, simulation, waveform, formal, equivalence, synthesis, and STA artifacts with exact identities.
3. Model effectiveness: controlled Codex skill-off/skill-on trials using the same model, prompt, tool access, budget, seeds, and hidden acceptance tests.

The 1.0 release establishes the first two and publishes the model-evaluation case manifest and protocol in `evals/`. Static keyword checks are not accepted as model evaluation. Post-1.0 workflow audits may demonstrate that Codex actually loads the skill and changes its verification behavior, but a small transparent task must not be generalized into a model-effectiveness uplift claim.

The public cases cover specification-to-RTL, repair, RTL/TB attribution, waveform localization, SystemVerilog semantics, and timing-aware refinement. Hidden answers must remain outside any retrieval namespace available to the evaluated run. Record failed and blocked runs, model/version, token and elapsed budgets, commands, tool versions, candidate hashes, and all hidden-test results.

GK/KY scoring can audit an explicit candidate/report directory, but repository auto-discovery must not be used as a release score because quarantined upstream projects may be misidentified as candidates. A score is reported only with the exact candidate path, task contract, logs, run records, and gate effects.

## Capturing the internal workflow safely

Codex JSONL is treated as an observable execution trace, not permission to expose private chain-of-thought. The public/sanitized layer retains only lifecycle counts, hashed thread identifiers, redacted commands, file changes, final agent messages, token usage, tool evidence, and grader results. Reasoning content is skipped. Raw JSONL stays in an ignored local directory and is not a release artifact.

An activation claim requires an exact read of `.agents/skills/rtl-ass/SKILL.md` or its references; reading an unrelated global `SKILL.md` does not count. An evidence-closure claim requires passing `run-evidence.json` records whose subject hashes include the final candidate and, for simulation, the unchanged supplied testbench. Correctness is decided independently by hidden simulation plus lint and synthesis, never by the agent's final statement.

Infrastructure failures remain visible and do not enter the valid denominator. A timeout under the declared budget is a valid task failure, even if the partial candidate later passes the external grader; report task completion and partial-candidate correctness separately. Report paired raw outcomes, evidence completeness, elapsed time, and token cost. With fewer than multiple diverse tasks, report workflow effects only and retain `effectiveness_status: not_evaluated` for general uplift.
