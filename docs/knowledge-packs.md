# Knowledge derivation and portable packs

Knowledge packs transport attributable text records; they do not train Codex and do not confer verification or promotion.

## Derivation

`kb derive` creates a `candidate` record from one exact non-tool-evidence source. It inherits source URI, revision, and license metadata, records the source content hash and derivation method, and creates a `derived-from` link in the same transaction. The allowed methods are `extract`, `generalize`, `normalize`, `repair`, and `summarize`.

```bash
rtl-ass kb derive RECORD_ID --db knowledge.db --namespace project:distilled \
  --actor curator --role design-pattern --language markdown \
  --title 'Ready/valid invariant' --summary 'Backpressure stability rule' \
  --content-file card.md --source-path cards/ready-valid.md --method generalize
```

Tool output cannot be authored as distilled knowledge or used as the sole derivation source. Evidence remains a separate `tool-evidence` record.

## Pack contract

`schemas/knowledge-pack.schema.json` defines the public 1.0 shape. Runtime validation additionally enforces UTF-8 byte bounds, exact root fields, safe identifiers, unique keys/links, role-compatible relationships, directory-contained `content_path` values, per-record SHA-256, and a semantic pack hash. `content_path` is resolved only while loading a pack file and is normalized to embedded content before import.

Import validates the complete pack before opening a database transaction. Records always enter the selected namespace as `raw`; relationships and audit events commit together or roll back together. An identical retry is audit-neutral. An identity collision with different immutable title, summary, license, or metadata is rejected.

Export requires unique explicit record IDs and permits only records with explicit `known`, non-`UNKNOWN` SPDX metadata. Unknown, incompatible, and not-applicable status remains local/quarantined and cannot be exported. The caller-supplied pack-level SPDX value does not replace per-record licensing and is not a legal compatibility determination. Review the resulting license set before redistribution.

```bash
rtl-ass kb pack-validate pack.json
rtl-ass kb import-pack pack.json --db knowledge.db --namespace org:review --actor importer
rtl-ass kb export-pack --db knowledge.db --record ID1 --record ID2 \
  --name reviewed-pack --pack-version 1.0.0 --description 'Reviewed patterns' \
  --license-spdx Apache-2.0 --output reviewed-pack.json
```
