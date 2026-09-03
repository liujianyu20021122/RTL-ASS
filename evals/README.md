# RTL-ASS model evaluation protocol

`cases.json` is the public, non-answer case manifest for controlled Codex skill-off/skill-on evaluation. It is not a benchmark score and must not be evaluated by keyword matching.

For each case, hold the Codex model/version, prompt, tool access, token and elapsed budgets, starting repository, and hidden tests constant. Hold a seed constant when the evaluated interface exposes one; `codex exec` currently does not, so repeated pairs are independent replications rather than deterministic seeded trials. The off condition receives no RTL-ASS skill or knowledge namespace. The on condition receives the released skill and only the namespaces declared for that case. Run at least five pairs before comparing pass rate, first-pass correctness, evidence completeness, regression rate, and cost.

Hidden tests, reference implementations, and adjudication notes must never enter a retrieval namespace visible to either condition. Preserve every candidate, command, tool version, artifact hash, timeout, infrastructure failure, and reviewer override. Report confidence intervals and raw paired outcomes; do not collapse correctness into a style score.

Validate the public manifest with:

```bash
PYTHONPATH=src python3 evals/validate_cases.py evals/cases.json
```

RTL-ASS 1.1 publishes both this protocol and the reviewed six-class workflow audit, while making no general model-uplift claim. The audit is published in
[`results/2026-09-01-codex-multitask-workflow-audit.md`](results/2026-09-01-codex-multitask-workflow-audit.md).

## Observable Codex workflow audit

`run_codex_ab.py` exercises any registered workflow fixture in isolated Git workspaces. It invokes `codex exec --json`, stores the raw JSONL only below the ignored output directory, and emits a sanitized report containing event counts, redacted commands, file changes, final agent messages, usage, skill activation signals, normalized evidence records, and an external hidden-test grade. Reasoning item content is never copied into the sanitized result. The report binds the fixture, prompt, hidden grader, harness, skill, runtime, and combined on payload by SHA-256.

Run a local five-pair audit with:

```bash
PYTHONPATH=src python3 evals/run_codex_ab.py \
  --output .rtl-ass/evals/fifo-paired-5 \
  --replicates 5 --parallel 1 --timeout 600 \
  --model gpt-5.6-sol --effort medium \
  --case repair-non-power-of-two-fifo
```

Command network access is disabled by default. If the host cannot initialize Codex's isolated loopback network namespace, `--sandbox-network` retains the `workspace-write` filesystem sandbox while explicitly enabling command network access. The report records this weaker isolation setting; use it only for local workflow diagnostics.

Select one of the six case IDs listed by `python3 evals/run_codex_ab.py --help`. There is deliberately no implicit all-case mode: each campaign receives a distinct output directory and report identity. Do not modify the runner, case registry, fixture, hidden grader, skill, or runtime while a campaign is running.

The audited reasoning-effort axis is `none`, `low`, `medium`, `high`, `xhigh`, and `max`. Treat model and effort selection as experimental parameters: screen configurations with one independent pair on representative cases, then run at least five fresh pairs for any configuration used in an effectiveness claim. Do not combine reports whose prompt, fixture, hidden grader, harness, Skill, or runtime hashes differ. Token counts and latency are reportable directly; monetary cost requires a separately dated price source and is never inferred by this harness.

The local mode uses Codex's `workspace-write` sandbox. It retains the host `CODEX_HOME` so Codex's trusted sandbox helper remains executable, ignores user configuration, disables plugins, and applies exact path-based `skills.config` exclusions to every host and repository Skill. The on condition therefore sees only the copied workspace RTL-ASS payload, while off sees no host RTL Skill.

Formal effectiveness runs use `--outer-bwrap` and an extracted release Skill. The host-created boundary exposes only the public workspace, an isolated authentication home, the Codex package, a read-only resolver file, and read-only open-tool installations; the private grader remains host-only. Open tools are discovered from the invoking environment's `PATH`; non-system installation prefixes are mounted read-only under stable sandbox paths, while `/usr` tools use the existing read-only system mount. This mode is always serialized across evaluator processes and requires `--parallel 1`. A root-created systemd cgroup caps CPU, memory, swap, process count, and total runtime before `bwrap` drops the agent to the invoking unprivileged user and group. A half-second resource monitor can terminate the complete unit before its hard memory ceiling or when host available memory reaches the declared floor. A separate transport monitor terminates a run after 120 seconds of continuous network errors; terminal transport failure is infrastructure evidence and cannot enter the effectiveness denominator. The raw JSONL and resource telemetry stay below the ignored campaign directory, while their hashes, peak values, cgroup events, and exact policies enter the sanitized result.

A formal campaign stops immediately after any infrastructure failure. The completed run retains its sanitized result and raw local artifacts, but the incomplete campaign emits no aggregate effectiveness report and must be restarted in a fresh output directory.

```bash
PYTHONPATH=src python3 evals/run_codex_ab.py \
  --output .rtl-ass/evals/fifo-release-paired-5 \
  --replicates 5 --parallel 1 --timeout 900 \
  --model gpt-5.6-sol --effort high \
  --outer-bwrap --skill-root build/extracted-skill/rtl-ass \
  --case repair-non-power-of-two-fifo
```

The workflow monitor reports attempted network/package acquisition, proprietary EDA, nested model/agent invocation, off-condition Skill leakage, protected-fixture edits, malformed trace lines, and evidence classes outside the case policy. Its `compliant` field is an audit result, not a substitute for the independent correctness grader. Monitoring is limited to observable Codex command and file-change events; it does not infer opaque behavior inside an arbitrary generated program.

Private fixtures are hidden only from each isolated Codex workspace during a run. Because they are published with the repository, this is a transparent regression/evaluation suite, not a secret or reusable benchmark. Five-pair results have wide confidence intervals and must be reported per task. Cross-task totals are descriptive only.

The public FST fixture can be regenerated with:

```bash
vcd2fst \
  evals/workflow_cases/waveform_first_divergence/private/priority_divergence_source.vcd \
  evals/workflow_cases/waveform_first_divergence/public/trace/priority_divergence.fst
```

Its committed identity is pinned at SHA-256 `c7df53e0361123cd071327a6f6e02e4360c546c7400a762ad31b8b1741ac8c32`. FST container bytes may differ across GTKWave versions, so the regression suite separately verifies the committed hash and compares bounded signal/event and first-divergence semantics for the source VCD, committed FST, and regenerated FST.
