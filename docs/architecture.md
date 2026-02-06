# RTL-ASS architecture

RTL-ASS has three deliberately separate layers.

1. The Codex skill supplies compact task routing and RTL-specific references. It never replaces Codex as the author or decision-maker.
2. Deterministic helpers inspect projects, discover open tools, index knowledge, and normalize evidence. They never choose RTL patches.
3. The local knowledge store holds content-addressed records, explicit RTL/TB roles, lifecycle state, provenance, verification summaries, and append-only audit events.

## Trust boundary

Imported GitHub or local content is untrusted data. Indexing reads text and metadata but does not execute RTL. Database transitions are centralized and transactional. Candidate verification is a dedicated atomic operation: validate the configured gate, create independent tool-evidence records, link them to the candidate, and transition the candidate. Direct transition to `verified` is rejected.

Non-passing runs use a separate atomic observation path. It stores immutable evidence without changing target state and requires explicit attribution. Only a real `fail` attributed to the target becomes a negative link; infrastructure and unresolved outcomes remain neutral observations so retrieval cannot silently turn tool failures into RTL rules.

## Knowledge identity

Content is identified by SHA-256 and stored once in the blob table. Records add namespace, role, source revision, license, metadata, and lifecycle context. Testbench and assertion records link to exact DUT content hashes rather than mutable filenames.

## Retrieval

The MVP uses SQLite FTS5 plus structured filters. Vector retrieval is deferred until it demonstrates measurable value over lexical and RTL-structural signals. Codex receives bounded result cards and decides whether to inspect or reuse them.

## Audit model

Each committed mutation appends one audit event in the same transaction. Audit rows cannot be updated or deleted. A multi-record verification workflow commits all record, link, transition, and audit events together or rolls all of them back. This provides a causal history without scattering defensive logging through command handlers.

Schema definition, audit-chain logic, migrations, record-store primitives, and public knowledge workflows have separate module ownership. Migrations are explicit version edges rather than compatibility heuristics. The v1-to-v2 edge rebuilds the audit table with non-null chain fields and validates the complete resulting chain inside the migration transaction.

## Verification evidence

The stable `evidence.py` facade delegates to simulation/lint, Yosys, and STA adapters. Shared bundles own ordered content identity, input-stability checks, artifact hashing, timeout normalization, and the common evidence contract, so tool modules do not grow competing policy implementations.

The current adapters execute Verilator lint, Icarus simulation, Yosys synthesis, bounded Yosys SAT assertion checks, Yosys equivalence, bounded VCD/FST queries, and OpenSTA. Every tool run binds commands, ordered input hashes, proof parameters, and ordered artifact hashes. FST is converted through a timeout- and byte-bounded `fst2vcd` stream while preserving original, converter, and converted identities. Formal runs reject an empty assertion scope and downgrade changed inputs to `blocked`; disproved assertions carry VCD counterexamples. Equivalence records distinct reference/implementation roles and labels depth greater than one as bounded-sequential, never unbounded. Verification rechecks raw artifacts and the original run-evidence JSON before and immediately after evidence records are written. OpenSTA requires a netlist, Liberty timing data, and SDC; negative slack is a failure and unconstrained endpoints block a timing-closure claim. Stronger proof backends remain future work. Evidence types stay separate so synthesis cannot be mistaken for functional, formal, or timing proof.

## Knowledge curation

Distillation is a transaction-owned workflow separate from raw ingest and tool evidence. A derived candidate inherits provenance and licensing, records its method and source content hash, and creates a `derived-from` link. Portable packs are strict, size-bounded, content-addressed containers; import validates every record and link before writes and always enters an explicit namespace as `raw`.

The upstream corpus adds a policy and lock layer before raw ingest. Policy must decide every inventoried source; the lock binds each admitted tracked file to repository identity, license review, role, byte count, and content hash. Import rechecks those identities and commits the complete corpus batch atomically. Source-specific namespaces, quarantine metadata, and explicit fixture/verification roles keep broad language corpora from becoming default RTL recommendations.
