# Codex RTL-ASS six-class workflow audit — 2026-09-01

## Decision

The RTL-ASS mechanism is real and observable: all 30 skill-on runs read or executed the isolated repository skill, all 30 produced the complete required structured evidence set, and none of the 30 skill-off runs showed skill activation or complete structured evidence. This is not merely inferred from the final answer.

General RTL correctness uplift is not established. The external graders accepted 30/30 skill-on candidates versus 28/30 skill-off candidates, while task completion was 29/30 on versus 23/30 off. The paired task outcomes were seven on-only, one off-only, 22 both, and zero neither. The sample is small, heterogeneous, and transparent; the result supports RTL-ASS as a Codex verification and evidence layer, not as a replacement coding agent or proof of universal RTL-generation improvement.

## Protocol and isolation

- `codex-cli 0.148.0`, `gpt-5.6-sol`, medium reasoning, five independent off/on pairs per case, and a 600-second per-run timeout.
- Identical prompt, public fixture, host open-source tools, model, and budget within each pair. `codex exec` exposed no seed, so the repetitions are independent rather than deterministically seeded.
- The off workspace did not contain RTL-ASS skill files or runtime. The on workspace received a copied repository skill and runtime. Child `PYTHONPATH` was removed to prevent the host checkout from leaking into off.
- Authentication was copied to a temporary per-run Codex home. User-global skills/configuration were not copied.
- Hidden graders and reference implementations stayed outside both agent workspaces. Graders independently compiled or analyzed the final candidate and checked protected-file hashes.
- Raw JSONL remains in ignored local storage. Sanitized reports retain observable commands, file changes, final messages, usage, evidence metadata, and grader output; reasoning item content is not retained.
- The host could not provide a nested Codex `workspace-write` sandbox, so the counted runs used `danger-full-access` inside externally isolated disposable workspaces. This limitation is material.

All six reports bind the same harness hash `7ea68fd2bbfdcc9aeb45f97847f0b0972fa08dc3139f8f8270ba93669d58e722` and stable on-payload hash `14eccf7a04e5db2a9a5bfce1092941d617098df2571db6729c9d1ef5ec514cea`.

## Results

`Correct` is the independent grader result. `Task` also requires timely Codex completion and the case deliverable. `Evidence` means the complete required set of current-candidate-bound structured records. Durations and input tokens are sums across five runs, not wall-clock campaign time.

| Case | Correct off→on | Task off→on | Evidence off→on | Duration off→on (s) | Input tokens off→on |
|---|---:|---:|---:|---:|---:|
| Ready/valid generation | 5→5 | 5→5 | 0→5 | 1482.917→1938.294 | 1,129,418→2,129,858 |
| NBA scoreboard attribution | 5→5 | 5→5 | 0→5 | 1127.288→1558.521 | 1,057,853→1,925,196 |
| Signed-width repair | 4→5 | 4→5 | 0→5 | 2179.558→2173.337 | 2,812,101→3,333,912 |
| Timing-aware refinement | 4→5 | 4→5 | 0→5 | 2248.074→1388.013 | 2,738,145→2,359,913 |
| FST first divergence | 5→5 | 0→5 | 0→5 | 1168.199→813.402 | 1,488,960→1,263,474 |
| Non-power-of-two FIFO repair | 5→5 | 5→4 | 0→5 | 1916.578→2277.415 | 1,837,134→3,382,473 |
| Descriptive aggregate | 28→30 | 23→29 | 0→30 | 10122.614→10148.982 | 11,063,611→14,394,826 |

For a per-case 5/5 proportion, the Wilson 95% interval is `[0.566, 1.000]`; 4/5 is `[0.376, 0.964]`; 0/5 is `[0.000, 0.434]`. The aggregate is descriptive only because the six task contracts and difficulty levels are heterogeneous.

Observed behavior:

- Ready/valid, attribution, and FIFO had correctness ceiling effects. RTL-ASS added reproducible evidence but increased input tokens in all three.
- Signed-width and STA each had one on-only correct/task-success pair. The sample is too small to separate a systematic effect from model variance.
- STA cut summed duration and input tokens substantially while emitting complete simulation/equivalence/synthesis/STA evidence in every run.
- Both conditions diagnosed all five FST traces correctly. Off never delivered the required native structured FST divergence record; on delivered and independently validated it in every run. This isolates a concrete waveform-tooling benefit from Codex's reasoning ability.
- FIFO on used more time and tokens, and one run exceeded 600 seconds after producing a correct candidate and complete evidence. This is a real stopping/efficiency failure.
- Across all cases, on used 30.11% more input tokens, 3.64% fewer output tokens, and 0.26% more summed duration. These mixed costs rule out a blanket efficiency claim.

## Audit defects found and corrected

The campaign was also used to attack the evaluator and helper rather than trust first-pass numbers.

1. Leaf-only waveform patterns such as `valid_i` did not match hierarchical signals. Query and divergence now support both full hierarchy and leaf globs, with real VCD/FST regression coverage.
2. Equivalence implicitly enabled Yosys undefined/X behavior, which could reject ordinary bit-domain algebraic rewrites. The evidence contract now records an explicit `defined` default and an opt-in `undefined` domain.
3. The off condition could inherit the host runtime through `PYTHONPATH`. Runs now copy runtime only into on and clear inherited `PYTHONPATH` for both child conditions.
4. FST grader status/kind recognition omitted native first-divergence records. Recognition and regression coverage were added.
5. Diagnosis correctness and required evidence delivery were initially conflated. Reports now expose `candidate_correct`, `deliverable_complete`, and `task_success` separately.
6. A successful compound command containing a failed `python3 -m rtl_ass --help` probe was miscounted as activation. Activation now requires the workspace helper path or a successful repository skill/reference read; the clean FST rerun measured off activation at 0/5.
7. Early four-case reports lacked a harness hash. They were not promoted as final results; all four were rerun with the frozen hashed harness used by FIFO and FST.
8. The public FIFO manifest still named formal as its minimum evidence while the executable protocol and historical grader required lint, simulation, and synthesis; supplemental formal was explicitly governed by a stopping rule. The stale manifest field was corrected to match the executed contract. Non-passing supplemental formal attempts remain visible and are not presented as passes.
9. Skill/runtime hashing and on-workspace copying initially included transient `__pycache__`/`.pyc` files, so clean-clone payload identity was unstable. Hashing now excludes bytecode and symlinks, copying excludes bytecode from both trees, and regressions prove normal/optimized compilation cannot change payload identity. All six final campaigns were rerun under the clean stable payload; earlier reports are audit history only.

## Report identities

| Case | Sanitized report SHA-256 |
|---|---|
| Ready/valid generation | `47e246cd3253a99cb701795d5cb63479944fe1b6248ed981457075f2c1326a8b` |
| NBA scoreboard attribution | `dce62d2f267586cbd9aa66e7d72120ea4fd34b0792be1a04bfdc18eaea385c62` |
| Signed-width repair | `c59f9bcc1abe18803c0de419505dd8bb09108b6e97a5fb51abc4fb14e7196a02` |
| Timing-aware refinement | `f696366ba08a6331469d3e5160082f70596bae646d6920517e7407ff79546207` |
| FST first divergence | `51f0ae80aa0892bf68566e9ecee2c50ce1d1efef90272e4e6d12d1a92a66fc26` |
| Non-power-of-two FIFO repair | `373dd6eb62efc76b7e34e658aaadc3d04423eb08126aa7a1055e533fe17bc8aa` |

The compact machine-readable result is `2026-09-01-codex-multitask-summary.json`. The raw local reports are deliberately not release artifacts because they contain bulky execution traces and environment-specific paths.

## Claim boundary

The result validates isolation, observable activation, evidence generation, and six first-party closed-loop workflows. It does not establish a universal correctness uplift, deterministic reproducibility, physical signoff quality, or performance on private industrial repositories. The public 1.0 case manifest therefore retains `effectiveness_status: not_evaluated` for a general model-uplift claim; this campaign records the narrower status `workflow_mechanism_validated_general_correctness_uplift_not_established`.
