# Audit model

RTL-ASS treats auditability as a cross-cutting invariant rather than a final report.

## Audited mutations

Database initialization, record creation, lifecycle transition, and record linking append one event in the same SQLite transaction as the mutation. Candidate verification combines evidence records, evidence links, the status transition, and their events in one transaction. A failed gate, changed artifact, invalid transition, or database failure appends no event and changes no state.

Schema migration is also transaction-owned. `kb migrate` supports only declared version edges; the v1-to-v2 edge requires the exact known audit shape, rebuilds the chain, appends its migration event, and verifies the complete chain before commit. Unknown versions, unknown columns, invalid historical JSON, or a failed final chain check leave the original schema and data intact.

Each event records actor, action, subject, previous/new state, timestamp, canonical input/output hashes, details, previous event hash, and current event hash. Event hashes use canonical JSON and SHA-256.

## Enforcement and detection

SQLite triggers reject ordinary update and delete operations on audit rows. `rtl-ass kb audit` recomputes the complete event chain from genesis and reports whether the chain is valid. Tests remove a trigger and edit history out of band to prove that chain verification detects the modification.

This is tamper-evident, not tamper-proof. A database owner can replace the entire database or recompute a new chain. Future organization deployments may anchor signed chain heads outside the database.

## Evidence identity

Tool evidence captures ordered source hashes before execution and checks them again after execution. It also hashes every raw log, executable, report, script, statistic, and netlist artifact listed by the adapter. If an input changes during the run, status becomes `blocked`. At knowledge verification time, artifact hashes and the original run-evidence JSON are checked twice around evidence-record insertion. Multi-file evidence has one bundle hash plus per-subject hashes; the gate requires the candidate's exact content hash among those subjects.

Non-passing observation uses the same artifact and run-evidence rechecks. Its attribution is stored on the relationship, not inside objective tool evidence. Identical retries are no-ops; attempting to re-attribute the same evidence/target pair differently is rejected rather than creating contradictory learning edges.

Knowledge derivation and pack import share the transaction boundary. Derived candidates record the source content hash and create their `derived-from` link atomically. Pack identity, contained paths, content hashes, licenses, roles, and relationships are validated before database writes; an identical retry adds no audit events, while immutable-field conflicts roll back the complete import.

## Corpus boundary

GitHub sources remain in quarantine. Automated license detection is a screening signal, never a legal decision. Manifest generation reads Git metadata, license text, and tracked paths but does not execute upstream source. Benchmark-like paths receive contamination labels and are excluded from evaluation retrieval by policy.

## Review focus

Reviewers should reject silent fallbacks, sample-specific branches, evidence claims without raw artifacts, status promotion without matching hashes, cross-namespace leakage, and duplicated validation logic outside the central policy layer.
