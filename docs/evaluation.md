# Evaluation policy

RTL-ASS separates three questions that are often incorrectly collapsed.

1. Helper correctness: unit, schema, transaction, optimized-runtime, and real open-tool integration tests.
2. Candidate RTL evidence: lint, simulation, waveform, formal, equivalence, synthesis, and STA artifacts with exact identities.
3. Model effectiveness: controlled Codex skill-off/skill-on trials using the same model, prompt, tool access, budget, seeds, and hidden acceptance tests.

The 1.0 release establishes the first two and publishes the model-evaluation case manifest and protocol in `evals/`. It does not publish or imply a skill-effectiveness uplift because no independent controlled Codex A/B campaign is part of this release. Static keyword checks are not accepted as model evaluation.

The public cases cover specification-to-RTL, repair, RTL/TB attribution, waveform localization, SystemVerilog semantics, and timing-aware refinement. Hidden answers must remain outside any retrieval namespace available to the evaluated run. Record failed and blocked runs, model/version, token and elapsed budgets, commands, tool versions, candidate hashes, and all hidden-test results.

GK/KY scoring can audit an explicit candidate/report directory, but repository auto-discovery must not be used as a release score because quarantined upstream projects may be misidentified as candidates. A score is reported only with the exact candidate path, task contract, logs, run records, and gate effects.
