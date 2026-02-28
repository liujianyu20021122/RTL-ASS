# RTL-ASS model evaluation protocol

`cases.json` is the public, non-answer case manifest for controlled Codex skill-off/skill-on evaluation. It is not a benchmark score and must not be evaluated by keyword matching.

For each case, hold the Codex model/version, prompt, selected or project-local verification flow, token and elapsed budgets, starting repository, and hidden tests constant. Hold a seed constant when the evaluated interface exposes one; `codex exec` currently does not, so repeated pairs are independent replications rather than deterministic seeded trials. The native condition receives no RTL-ASS skill or knowledge namespace. The primary product condition receives the released retrieval-first Skill and only the relevant calibrated namespaces declared for that case. Empty and irrelevant calibrated namespaces are separate retrieval controls. Run at least five pairs before comparing pass rate, first-pass correctness, evidence completeness, regression rate, and cost.

Do not enable RTL-ASS EDA adapters in a primary retrieval comparison merely because they are available. Use the same user-selected or project-local commands in every condition. A separate fallback-policy case may expose named adapters only after its prompt includes the required explicit user confirmation.

Retrieval comparisons accept an audited SQLite database, not a raw portable pack. The database must contain one to three contamination-reviewed `verified` or `promoted` cards in `eval:retrieval`; raw imports must first pass normal curation and verification outside the evaluated task. Every database is paired with a treatment manifest that binds the exact case hashes and card-content hashes, and labels the human-reviewed judgment as `relevant` or `plausible-irrelevant`. The manifest remains outside the Codex workspace. Use `--ablation retrieval` for Skill-with-empty versus Skill-with-treatment, `--ablation product` for native Codex versus Skill-with-relevant-treatment, and retain `--ablation skill` only as the diagnostic no-knowledge Skill comparison. Any attempted RTL-ASS EDA-adapter command makes a retrieval or product run workflow-noncompliant, including failed attempts; read-only `kb`, manifest, inspection, and evidence-validation operations remain distinguishable.

The on condition must retain a valid calibrated receipt. A relevant treatment must also include an observable
`kb show --include-content` read of a returned card. A reviewed plausible-irrelevant hit may be rejected from the
bounded receipt metadata without opening it; the report still distinguishes returned, opened, and uninspected
records. Missing treatment metadata uses the conservative relevant-card rule.

The signed-width fixture includes two project-local calibration treatments. The relevant treatment exhaustively checks all signed 4-bit operand pairs and requires detection of a narrow-intermediate mutation. The plausible-irrelevant treatment verifies a ready/valid payload-width card with a passing baseline and requires rejection of a backpressure mutation; it shares surface terms such as width, valid, reset, and latency but contains no signed-arithmetic rule. Both invoke Icarus Verilog directly and write only ignored local artifacts; they are evaluation curation, not RTL-ASS EDA fallback databases shipped to users:

```bash
PYTHONPATH=src python3 evals/retrieval_packs/signed-width/calibrate.py \
  --treatment relevant \
  --output .rtl-ass/evals/signed-width-calibrated.db
PYTHONPATH=src python3 evals/retrieval_packs/signed-width/calibrate.py \
  --treatment plausible-irrelevant \
  --output .rtl-ass/evals/signed-width-irrelevant.db
```

The primary product pair uses the relevant manifest:

```bash
PYTHONPATH=src python3 evals/run_codex_ab.py \
  --output .rtl-ass/evals/signed-width-product-5 \
  --replicates 5 --parallel 1 --timeout 900 \
  --model gpt-5.6-sol --effort high --outer-bwrap \
  --case systemverilog-signed-width --ablation product \
  --retrieval-database .rtl-ass/evals/signed-width-calibrated.db \
  --retrieval-treatment-manifest evals/retrieval_packs/signed-width/relevant-treatment.json
```

Hidden tests, reference implementations, and adjudication notes must never enter a retrieval namespace visible to either condition. Preserve every candidate, command, tool version, artifact hash, timeout, infrastructure failure, and reviewer override. Report confidence intervals and raw paired outcomes; do not collapse correctness into a style score.

Validate the public manifest with:

```bash
PYTHONPATH=src python3 evals/validate_cases.py evals/cases.json
```

RTL-ASS 1.1 publishes both this protocol and the reviewed six-class workflow audit, with task completion improving from 23/30 to 29/30 in those cases. The audit is published in
[`results/2026-09-01-codex-multitask-workflow-audit.md`](results/2026-09-01-codex-multitask-workflow-audit.md).

The first treatment-bound product and plausible-irrelevant development observations, their forward-policy replay,
and the resource-protected follow-up stop are recorded in the
[`2026-09-04 causal retrieval controls`](results/2026-09-04-causal-retrieval-controls.md). They validate and repair
the experimental mechanism and retain the observed lint failures and additional cost.

The complete signed-width product, relevant, and plausible-irrelevant results are recorded in the
[`2026-09-05 frozen causal retrieval campaign`](results/2026-09-05-frozen-causal-retrieval-campaign.md). The task
reached 5/5 correctness in every condition. Relevant retrieval reduced aggregate time by 2.27% with mixed paired
timings and higher token use; the product and irrelevant-card contrasts cost more. See the
[current measured-effects summary](../docs/evaluation.md#measured-effects-and-scope) for baselines and scope.

## Observable Codex workflow audit

File-level source inspection and independently checked application are documented in
[the file-application protocol](../docs/file-application-evaluation.md). Its `packet-tag-skid` case uses an isolated,
behavior-calibrated upstream RTL record, and does not count successful retrieval or self-reported use as proof
of correct adaptation.

`run_codex_ab.py` exercises any registered workflow fixture in isolated Git workspaces. It invokes `codex exec --json`, stores the raw JSONL only below the ignored output directory, and emits a sanitized report containing event counts, redacted commands, file changes, final agent messages, usage, skill activation signals, normalized evidence records, and an external hidden-test grade. Reasoning item content is never copied into the sanitized result. The report binds the fixture, prompt, hidden grader, harness, skill, runtime, and combined on payload by SHA-256.

Run a local five-pair audit with:

```bash
PYTHONPATH=src python3 evals/run_codex_ab.py \
  --output .rtl-ass/evals/fifo-paired-5 \
  --replicates 5 --parallel 1 --timeout 600 \
  --model gpt-5.6-sol --effort medium \
  --case repair-non-power-of-two-fifo
```

Command network access is disabled by default. If the host cannot initialize Codex's isolated loopback network namespace, `--sandbox-network` retains the `workspace-write` filesystem sandbox while explicitly enabling command network access. The report records this weaker isolation setting; use it only for local workflow diagnostics. This mode still requires the host to support Codex's own sandbox; it is not valid inside another namespace that forbids nested `bwrap`. Use the audited `--outer-bwrap` mode for formal runs in such an environment.

Select one of the seven case IDs listed by `python3 evals/run_codex_ab.py --help`. There is deliberately no implicit all-case mode: each campaign receives a distinct output directory and report identity. Do not modify the runner, case registry, fixture, hidden grader, skill, or runtime while a campaign is running.

Repository-scale cases use `--soc-case` together with a local `--source-repository`. The runner reads only pinned Git objects, verifies the declared commit/tree/file and hidden-test identities, materializes a fresh full-repository fixture below the ignored output directory, and keeps that source store outside the agent sandbox. These cases follow [the large-SoC protocol](../docs/soc-evaluation.md); one pair is only a harness smoke.

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
