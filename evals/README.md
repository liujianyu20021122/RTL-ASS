# RTL-ASS model evaluation protocol

`cases.json` is the public, non-answer case manifest for controlled Codex skill-off/skill-on evaluation. It is not a benchmark score and must not be evaluated by keyword matching.

For each case, hold the Codex model/version, prompt, tool access, token and elapsed budgets, starting repository, and hidden tests constant. Hold a seed constant when the evaluated interface exposes one; `codex exec` currently does not, so repeated pairs are independent replications rather than deterministic seeded trials. The off condition receives no RTL-ASS skill or knowledge namespace. The on condition receives the released skill and only the namespaces declared for that case. Run at least five pairs before comparing pass rate, first-pass correctness, evidence completeness, regression rate, and cost.

Hidden tests, reference implementations, and adjudication notes must never enter a retrieval namespace visible to either condition. Preserve every candidate, command, tool version, artifact hash, timeout, infrastructure failure, and reviewer override. Report confidence intervals and raw paired outcomes; do not collapse correctness into a style score.

Validate the public manifest with:

```bash
PYTHONPATH=src python3 evals/validate_cases.py evals/cases.json
```

RTL-ASS 1.0 publishes the protocol but makes no controlled model-uplift claim.

## Observable Codex workflow audit

`run_codex_ab.py` exercises the transparent non-power-of-two FIFO repair fixture in isolated Git workspaces. It invokes `codex exec --json`, stores the raw JSONL only below the ignored output directory, and emits a sanitized report containing event counts, redacted commands, file changes, final agent messages, usage, skill activation signals, normalized evidence records, and an external hidden-test grade. Reasoning item content is never copied into the sanitized result.

Run a local five-pair audit with:

```bash
PYTHONPATH=src python3 evals/run_codex_ab.py \
  --output .rtl-ass/evals/fifo-paired-5 \
  --replicates 5 --parallel 2 --timeout 600 \
  --model gpt-5.6-sol --effort medium
```

The default `workspace-write` sandbox should be used. If an outer container prevents Codex from creating its nested sandbox, `--sandbox danger-full-access` is permitted only in an externally isolated disposable environment and must be disclosed as a limitation. Authentication is copied into a per-run temporary Codex home and removed after the run, which prevents user-global skills and configuration from contaminating the off condition.

The included private testbench is hidden only from each isolated Codex workspace during a run. Because it is published with the repository, this is a transparent regression/evaluation fixture, not a secret or reusable benchmark. A small single-task campaign can establish workflow activation and evidence behavior, but cannot establish general RTL correctness uplift.
