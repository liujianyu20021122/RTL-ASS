# RTL knowledge governance

## Purpose

The index gives Codex relevant, attributable context. It does not train model weights and must not override the current specification.

## Record roles

Use explicit roles: `rtl-design`, `testbench`, `assertion`, `reference-model`, `fixture`, `design-pattern`, `verification-pattern`, `bug-fix`, and `tool-evidence`. Link records by exact content identity rather than filenames alone.

## Lifecycle

Allowed forward transitions are:

```text
raw -> analyzed -> candidate -> verified -> promoted
  \         \           \          \        \
   +----------+-----------+----------+-------> deprecated
```

- `raw`: imported with provenance but not analyzed.
- `analyzed`: structural metadata extracted.
- `candidate`: considered useful but not sufficiently verified.
- `verified`: required configured evidence passed.
- `promoted`: explicitly approved for default retrieval preference.
- `deprecated`: retained for history but not recommended.

Do not promote automatically. Corrections append audit events; they do not rewrite history.

## Distillation and portable packs

Create a distilled record with `kb derive`, not by overwriting an imported source. The derived candidate must link to the exact source content hash, retain its license/provenance, state one method (`extract`, `generalize`, `normalize`, `repair`, or `summarize`), and remain independently reviewable. Tool evidence cannot be the sole source of an engineering rule.

Validate a portable pack before import. Import into an explicit namespace as `raw`; do not let pack metadata grant `verified` or `promoted`. Reject path escapes, changed content hashes, incompatible roles, unknown redistribution terms for public export, and identity collisions with different immutable metadata. The pack-level license is a declaration, not a replacement for per-record review.

## Retrieval

Search the project namespace first, then explicitly selected user, organization, or built-in namespaces. Request a small top-k set. Use `--match all` for a precise short query and explicit `--match any` for exploratory multi-term retrieval; there is no hidden fallback between them. Prefer matching role, language, interface/protocol, clock/reset assumptions, and verification state over textual similarity alone. Inspect source, license, limitations, and negative evidence before reuse.

For material work, write the search result as a retrieval receipt with the exact actor, query, namespaces, filters, limit, ordered record IDs, content hashes, provenance, license state, and ranking data. A returned summary is not evidence that Codex inspected the record: use `kb show <id> --include-content` only for selected results. Keep the receipt with task artifacts so evaluation can distinguish retrieval, content inspection, and actual correctness.

Measure retrieval value with a paired retrieval-off/retrieval-on experiment that keeps the Skill, prompt, model, effort, tools, public fixture, grader, and resource policy fixed. The on-only pack must be bounded, license-compatible, hash-distinct from public and hidden task artifacts, and manually reviewed to contain no task source, test, reference implementation, expected patch, or grader output. Retrieval occurrence or corpus size alone is not an improvement claim.

## GitHub corpus

Pin repository revision and record retrieval date, source URL, file hash, license decision, role, and benchmark-contamination status. Require an explicit decision for every inventoried source and a distinct namespace for every admitted source. Unknown or incompatible licenses remain quarantined. Preserve original source separately from distilled knowledge cards. Do not publish private or restricted source through the index.

For a reviewed local corpus, build `corpus/curated-lock.json` with `corpus lock`, then use `kb import-corpus` and inspect `kb stats`. Treat the lock as provenance, not correctness: import remains `raw`, source trees and the database remain local, and benchmark fixtures must stay outside default design retrieval. A repeated identical import should be audit-neutral; any changed revision, license, path, byte count, hash, or immutable record identity must stop the batch.

## Promotion evidence

Moving a candidate to verified requires the dedicated `kb verify` operation and explicit passing evidence whose ordered `subject_hashes` include that candidate's exact content hash. Apply the configured evidence kinds for the record role. Recheck ordered artifact hashes and the original run-evidence JSON, create separate `tool-evidence` records with `evidence-for` links, and commit those mutations with the transition. A multi-file run keeps a separate bundle `input_hash`; do not compare that bundle identity to one source file. Moving verified to promoted also requires a redistributable license decision or an explicitly non-redistributed internal scope plus review.

Record executed non-passing runs through `kb observe` and choose an attribution explicitly. Only `fail` plus `target` creates `negative-for`. Use `testbench`, `specification`, `constraints`, `infrastructure`, or `unattributed` when root cause is elsewhere or unresolved; these remain `evidence-for` and do not alter target lifecycle state. Never attribute `timeout` or `blocked` to the target. Conflicting re-attribution requires a new review decision rather than parallel contradictory links.
