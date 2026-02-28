# Calibrated source-file application: development observation

Experiment: 2026-09-05. Documentation review: 2026-09-07.

One `packet-tag-skid` pair recorded a modest elapsed-time improvement with a relevant calibrated RTL source:
510.611 to 466.658 seconds (8.61% lower), with 21.75% fewer input tokens. Both candidates passed the frozen
grader. This is a development observation under workflow policy 1.5; corrected-grader replay and final regression
closure remain pending. It is not a completed current-version acceptance gate.

## Comparison and results

Both conditions loaded the same extracted RTL-ASS Skill and used the direct project-local open-source flow.
The control received an empty index; the treatment received one behavior-calibrated `axis_register.v` record.
This measures the reference contribution within the Skill, not native Codex versus RTL-ASS.
The model was `gpt-5.6-sol`, high effort, with `codex-cli 0.153.4`. One serial pair ran under outer `bwrap` and
systemd resource supervision with a 900-second per-run budget. Neither agent invoked an RTL-ASS EDA adapter.

| Metric | Skill + empty | Skill + relevant file |
|---|---:|---:|
| Frozen-grader candidate correctness | pass | pass |
| Deliverable complete / workflow compliant | yes / yes | yes / yes |
| Elapsed time | 510.611 s | 466.658 s |
| Input tokens | 730,113 | 571,324 |
| Output tokens | 19,139 | 17,398 |
| Failed shell commands | 4 | 1 |
| Records returned / content-bound reads | 0 / 0 | 1 / 1 |
| Supported application declarations | 0 | 1 |

Output tokens decreased 9.10%. Failed shell commands include infrastructure/command mistakes and are not an RTL
defect count. Each candidate passed strict lint and five constraints at three parameter settings under the frozen
grader. Both runs recorded zero cgroup swap and memory-limit/OOM events.

## Observable use and provenance

The treated run read the complete source with a matching content hash and declared application of its generic
main-register-plus-skid-register handshake pattern to `rtl/packet_tag_skid.sv`. Its declaration linked stall
stability, reset, registered boundary and throughput to passing independent constraint checks. Packet arithmetic
and interface/reset adaptations were declared as derived from the task specification. The application audit joins
the receipt, source read, declaration, final candidate hash and constraint results; it does not inspect the model's
private reasoning or attribute all elapsed-time differences to the reference.

The source is MIT-licensed, pinned to upstream revision `48ff7a7e2ef782cf778d47910cf85835c64b1bce` and
content hash `599fde2d6c2d806643bbffb7c444297e69a71871f962d4b741ec1914342e0d39`.
The isolated evaluation record is `128d3eb491e73cc6f943a61aa46251ad`; its behavioral calibration did not modify
the main corpus. Source acquisition and calibration are defined by the
[pinned source manifest](../retrieval_packs/axis-register/source.json) and
[file-application protocol](../../docs/file-application-evaluation.md).

## Retained identities and follow-up

The ignored local report is `build/file-application-smoke-20260905/report.sanitized.json`.
Its embedded canonical report hash is
`c59662a03da95e7a0fd2bc9c3f3ba1645ccef89e44de1023359fdc86d5552e51`.
The frozen hidden-grader hash is
`ad572fcf48928dddda04ac026f15888a9dab05443933bbae7adddc2825a01909`;
the evaluation database hash is
`1ea354b29cbcb09737f66b59d0456321fce71ab777f94d2c5f0ef0f72a4f2562`.
Raw traces, database bytes and grader artifacts remain local, not redistributed with this summary.

Subsequent audit corrected handshake-acceptance timing, strengthened the output-data combinational-boundary
check, held stimulus until acceptance, adjusted the reset-fill check, and added detection of undeclared content
use. Eight targeted tests passed; the forward workflow policy is now 1.6. The owner deferred corrected-grader
replay and final regression closure. The original policy-1.5 report remains unchanged, and this documentation
update neither reruns the experiment nor transfers its pass status to the corrected grader.
