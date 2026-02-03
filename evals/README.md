# RTL-ASS model evaluation protocol

`cases.json` is the public, non-answer case manifest for controlled Codex skill-off/skill-on evaluation. It is not a benchmark score and must not be evaluated by keyword matching.

For each case, hold the Codex model/version, prompt, tool access, token and elapsed budgets, seeds, starting repository, and hidden tests constant. The off condition receives no RTL-ASS skill or knowledge namespace. The on condition receives the released skill and only the namespaces declared for that case. Run at least five paired seeds before comparing pass rate, first-pass correctness, evidence completeness, regression rate, and cost.

Hidden tests, reference implementations, and adjudication notes must never enter a retrieval namespace visible to either condition. Preserve every candidate, command, tool version, artifact hash, timeout, infrastructure failure, and reviewer override. Report confidence intervals and raw paired outcomes; do not collapse correctness into a style score.

Validate the public manifest with:

```bash
PYTHONPATH=src python3 evals/validate_cases.py evals/cases.json
```

RTL-ASS 1.0 publishes the protocol but makes no controlled model-uplift claim.
