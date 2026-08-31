# Security policy

RTL-ASS 1.x receives security fixes. Report vulnerabilities privately through GitHub's security advisory interface; do not include private RTL, credentials, or proprietary tool output in a public issue.

The primary trust boundaries are untrusted RTL/corpus files, knowledge-pack paths and JSON, SQLite state, subprocess arguments, waveform expansion, and evidence artifacts. Indexing never executes RTL. Tool execution occurs only through explicit verification commands, uses argument arrays without a shell, applies timeouts, and hashes inputs and artifacts. FST conversion has a strict byte ceiling and timeout.

The SQLite audit chain detects ordinary history edits but cannot protect against an owner replacing the complete database. Users needing stronger assurance should anchor database and release hashes in an independently controlled system.
