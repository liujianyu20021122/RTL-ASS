# Reviewed local corpus

This directory contains metadata, never copied upstream HDL.

- `upstream-sources.json` inventories 21 research sources with immutable revisions, license screening, HDL/TB counts, and benchmark-contamination signals.
- `ingestion-policy.json` makes an explicit include/exclude decision for every source. Seven pinned, reviewed repositories are admitted and fourteen remain excluded.
- `curated-lock.json` binds the admitted 1,429 Verilog/SystemVerilog files to exact repository, revision, path, byte count, content hash, role, license review, and structural inspection metadata.

The lock is reproducible only against the ignored `research/upstream/` checkouts:

```bash
rtl-ass corpus lock corpus/ingestion-policy.json \
  --source-root research/upstream --output corpus/curated-lock.json
rtl-ass kb init --db .rtl-ass/index.db --actor corpus-review
rtl-ass kb import-corpus corpus/curated-lock.json \
  --source-root research/upstream --db .rtl-ass/index.db --actor corpus-review
rtl-ass kb stats --db .rtl-ass/index.db
```

Lock creation and import reject a changed Git revision/origin, tracked modifications, untracked license file, changed license or HDL hash, symlink, path escape, overlapping selection, namespace reuse, resource-limit violation, and identity conflict. The complete record batch commits atomically and is followed by audit-chain verification. An identical retry is audit-neutral.

All imported content starts `raw` in a source-specific `corpus:*` quarantine namespace. A lock is provenance evidence, not correctness evidence. Benchmark fixtures (`sv-tests`) and UVM/templates are isolated by role and must not be treated as synthesizable design patterns. Promotion still requires explicit derivation, executable evidence, license review, and human approval. See [corpus governance](../docs/corpus.md).
