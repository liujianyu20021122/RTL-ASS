# Calibrated retrieval-first signed-width smokes

Date: 2026-09-04

These development smokes test whether Codex can consume one independently calibrated RTL knowledge card while keeping RTL authorship and the direct project-local open-source verification flow unchanged. They are one-pair observations, not a general effectiveness claim.

## Frozen inputs and isolation

- Case: `systemverilog-signed-width`
- Model: `gpt-5.6-sol`, reasoning effort `medium`
- Codex: `codex-cli 0.152.1`
- Isolation: serialized outer `bwrap`, capability drop, systemd cgroup supervision, 600-second per-run limit
- Retrieval database SHA-256: `89856f7b8981141cc10c021e00c1fd5ac749b7f0887eadff6081de20446b81e1`
- Database audit: seven valid append-only events; one `verified` design-pattern card; no direct task-artifact hash overlap
- Calibration: direct Icarus execution exhaustively checked all signed 4-bit operand pairs and required detection of a narrow-intermediate mutation. The database and evidence remain ignored local artifacts.

The off condition received the same Skill and an empty `eval:retrieval` database. The on condition received the exact calibrated database bytes. Both conditions were forbidden from invoking RTL-ASS EDA adapters and used direct Icarus, Verilator, and Yosys commands.

## Results

| Pair | Condition | External correctness | Time (s) | Input / output tokens | Retrieved / inspected calibrated records | Adapter attempts |
|---|---|---:|---:|---:|---:|---:|
| 1 | empty control | pass | 339.394 | 611,677 / 11,940 | 0 / 0 | 0 |
| 1 | relevant card | fail: strict lint | 337.163 | 742,454 / 13,200 | 1 / 1 after policy-2.1 replay | 0 |
| 2 | empty control | pass | 367.600 | 777,122 / 13,764 | 0 / 0 | 0 |
| 2 | relevant card | pass | 392.466 | 831,959 / 13,885 | 1 / 1 | 0 |

In pair 1, the relevant-card candidate widened the addition but not the comparison thresholds. Visible and hidden simulation, synthesis, and four-edge bounded equivalence passed, but independent Verilator lint rejected two `WIDTHEXPAND` diagnostics. The card itself explicitly required compatible comparison widths, so this was incomplete application of retrieved guidance rather than incorrect card content. The Skill now requires a pre-verification check of every decision-relevant constraint in selected records.

In pair 2, both candidates passed independent strict lint, visible and hidden simulation, synthesis, and bounded equivalence. The relevant-card candidate widened the arithmetic operands and both comparison thresholds. Relative to its paired empty control, it used 24.866 more seconds (+6.8%), 54,837 more input tokens (+7.1%), and 121 more output tokens (+0.9%). A single independent pair cannot estimate expected overhead or attribute the corrected candidate causally to retrieval.

## Evaluator defects found and corrected

1. A local diagnostic run placed Codex's own `workspace-write` sandbox inside an environment that rejected nested `bwrap`; both candidates remained unchanged and the evaluator correctly excluded them as infrastructure failures. Formal runs use the audited outer boundary with Codex's inner sandbox disabled.
2. Observable command parsing did not normalize leading shell environment assignments. Consequently, `PYTHONPATH=src python3 -m rtl_ass kb show ... | tee ...` was executed successfully but not counted as a content read, and similarly prefixed adapter commands could evade classification. One shared normalizer now feeds evidence, policy, Skill-signal, and RTL-ASS command classifiers.
3. An empty status-filtered search was initially counted as a calibrated receipt because universal status validation is vacuously true for an empty result set. Policy 2.1 requires at least one returned record for calibrated coding guidance.
4. After that correction, the empty control was temporarily required to produce an impossible non-empty calibrated receipt. Workflow policy 1.2 now requires a valid empty-control receipt off and a non-empty calibrated receipt plus content inspection on. Replaying both pair-2 traces under policy 1.2 yields zero violations in both conditions.

The immutable pre-correction sanitized reports remain local. Pair 1 has embedded report hash `d8b7e4c9cfa12b806846ce0616d681bc62c0699c2e5de9b4fac53d9c24182c5b` and report-file SHA-256 `401a14ccbe390da1c1fd270b1e2836738cee7186d0277b8bec646a55ebeeac84`. Pair 2 has embedded report hash `2d7cc6e1bfd14531f8938c24a2da05de8cc1ff80d323e2e691d0cd068b15a73e` and report-file SHA-256 `2c6e757076201508d768794037f64598c51fca800ff103407e635cbd089dfa1b`.

## Conclusion and remaining work

The smokes establish that the corrected workflow can retrieve and inspect a verified card without invoking RTL-ASS EDA adapters, and that the card can support a fully passing candidate. They also retain a real partial-application failure. They do not establish correctness uplift or efficiency improvement. The next effectiveness gate is at least five fresh pairs per accepted contrast, followed by relevant-versus-plausible-irrelevant controls and additional task classes.
