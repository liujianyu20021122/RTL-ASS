---
name: rtl-ass
description: Retrieve audited RTL design, testbench, assertion, and bug-pattern knowledge for Codex, with vendor-neutral Verilog/SystemVerilog guidance and an explicitly authorized open-source verification fallback. Codex remains the RTL author and decision-maker.
---

# RTL-ASS

RTL-ASS is retrieval-first. Its primary job is to give Codex small, provenance-bearing, calibrated RTL references that improve Codex's own reasoning and coding. It does not replace Codex, generate a hidden patch, or impose its open-source EDA adapters over a user-selected or project-local flow.

## Retrieve before coding

For an RTL generation, analysis, debug, verification, or optimization task:

1. Preserve the current specification, language, interface, latency, protocol, clock/reset behavior, tool choice, and verification scope.
2. Form a compact query from the design role, protocol or block type, failure symptom, clock/reset assumptions, and relevant SystemVerilog semantics.
3. If an in-scope RTL-ASS database exists, inspect its audited statistics and explicit namespaces. Search `promoted` records first and then `verified` records when no relevant promoted result exists. Search only the project namespace and explicitly applicable user, organization, or built-in namespaces; never search every namespace implicitly.
4. Retain every retrieval receipt, keep each result list at three records or fewer, and open full content for at most three selected hits in total. Prefer cross-project design patterns, bug fixes, assertions, testbenches, and negative evidence whose assumptions match the task. Do not retrieve `raw` or `candidate` records as coding guidance unless the user explicitly asks for unverified research material.
5. Classify each opened hit against a concrete design decision as applicable, partially applicable, or inapplicable. A lexical hit rejected as inapplicable is a no-relevant-result outcome: it must not substitute for a material conditional reference below or influence the patch.
6. Treat every applicable record as reference context, not as the current specification or an automatic patch. Codex independently reasons about the design and writes the smallest coherent change. Before verification, recheck the patch against each decision-relevant constraint in the selected records; satisfy it or record why it does not apply.

If no database exists or no calibrated record is relevant, state that bounded result and continue with Codex's own RTL reasoning. Do not initialize, ingest, derive, verify, promote, or broaden a database as a side effect of an ordinary coding task.

Read [knowledge-governance.md](references/knowledge-governance.md) before retrieval or any requested curation. Use these RTL references only when their subject is material:

- architecture or coding decisions: [rtl-design.md](references/rtl-design.md)
- ambiguous task class or evidence need: [task-routing.md](references/task-routing.md)
- testbench, assertion, or verification semantics: [verification.md](references/verification.md)
- real waveform diagnosis: [waveform-debugging.md](references/waveform-debugging.md)
- formal, synthesis, or STA claims: [synthesis-sta.md](references/synthesis-sta.md)

Do not load all references at task start. Retrieve first, then load at most the guidance needed for the current decision. If retrieval returns no applicable card, still load the one conditional reference whose subject materially governs that decision; an irrelevant database hit must not suppress it.

## Respect the selected verification flow

RTL-ASS open-source EDA adapters are a fallback, not the default workflow. Apply this precedence:

1. Use the exact tool or verification flow selected by the user.
2. Otherwise use an applicable documented project-local flow that the user has not forbidden.
3. Only when executed verification is required, no tool was selected, and no applicable project-local flow is usable or permitted, ask the user to confirm that no other local tool or flow should be used because it is unavailable or disallowed, and name the RTL-ASS fallback adapter you propose. Do not run that adapter until the user confirms both boundaries. An explicit request to use an RTL-ASS verification helper or named backend is itself a user-selected flow and needs no second confirmation.

If confirmation is unavailable or denied, do not substitute another tool silently. Report verification as `not_evaluated` with the exact missing or disallowed boundary. Read [tool-selection.md](references/tool-selection.md) when choosing, proposing, or using a verification tool; it is the canonical inventory of integrated and discovery-only tools.

Read-only knowledge search, record inspection, project inspection, manifest validation, and evidence validation do not execute EDA and are not fallback adapter use. They still must remain bounded and relevant; do not run `doctor`, repository-wide inspection, or evidence planning merely because the commands exist.

## Verification behavior

When using the user-selected or project-local flow, preserve its source order, libraries, includes, defines, parameters, top, scripts, and constraints. Report the exact commands and artifacts actually used. Do not rerun the same check through RTL-ASS solely to obtain its JSON format.

When the user has authorized the RTL-ASS fallback:

- reproduce a material baseline failure before changing the supplied checker;
- use one retained CompileManifest for a configured or multi-file closure;
- run only the lowest-cost evidence needed for the named claim;
- inspect real statuses and retain current inputs and artifacts;
- stop after the required claims pass; and
- identify every unverified boundary in the final response.

Compilation, simulation, waveform, formal, equivalence, synthesis, and STA remain separate evidence classes. Never claim waveform analysis without a real waveform. Never claim STA closure without an executed timing engine, mapped netlist, Liberty data, and constraints. A helper produces evidence; it never decides or applies the RTL patch.

## Bounded knowledge commands

Invoke the hash-verifying launcher beside this `SKILL.md`; never assume an installed `rtl-ass` executable or an
importable `rtl_ass` module is on `PATH`. Substitute the actual directory containing this Skill when it is not
repository-local. Prefer the configured database path and explicit namespaces. Repository-local examples:

```bash
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py kb stats --db .rtl-ass/index.db
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py kb search 'ready valid backpressure' --db .rtl-ass/index.db \
  --namespace project:current --status promoted --match any --limit 3 \
  --actor codex --output artifacts/rtl-ass/retrieval-promoted.json
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py kb search 'ready valid backpressure' --db .rtl-ass/index.db \
  --namespace builtin:starter --status verified --match any --limit 3 \
  --actor codex --output artifacts/rtl-ass/retrieval-verified.json
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py kb show <record-id> \
  --db .rtl-ass/index.db --include-content
```

Imported content is not calibrated merely because it is indexed. Preserve namespace isolation, source revision, content hash, license status, limitations, verification state, and negative evidence. Never expose private records through a broader namespace or retrieve benchmark answers while evaluating that benchmark.
