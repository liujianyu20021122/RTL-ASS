# Release process

RTL-ASS uses semantic versioning. Schemas with `schema_version: 1.0`, CLI command names, evidence keys, knowledge-pack identity rules, and database migration edges are public compatibility contracts for the 1.x line.

## Release gate

1. Freeze `PLAN.md`, `CHANGELOG.md`, package version, and skill contract.
2. Run compilation, both normal and optimized test suites, Ruff format/lint, strict mypy across all tracked Python modules in `src`, `tests`, `tools`, and `evals`, JSON Schema validation, and Skill Creator validation.
3. Run the representative starter RTL through Verilator, Icarus, Yosys synthesis, and bounded formal; run the checked fixtures through equivalence, waveform/FST, and OpenSTA.
4. Validate and atomically import the starter pack; verify its audit chain.
5. Build wheel, sdist, standalone skill archive, SPDX SBOM, and checksums in a clean output directory.
6. Install the wheel into a new virtual environment and run the installed CLI plus the standalone skill launcher.
7. Inspect wheel/sdist contents, run `twine check`, and confirm no generated database/waveform, cache, research checkout, credential file/value, absolute workstation path, or proprietary dependency is shipped. Declared first-party evaluation VCD/FST fixtures are allowed and must be listed by the packaging audit.
8. Confirm `v1.1.0` is absent locally and remotely, commit the reviewed release candidate, and create an annotated local tag only after approval.
9. After explicit publication approval, push `main` and `v1.1.0`, create the GitHub release, upload all five assets, and verify the remote commit, tag, asset names, and hashes. Never move or replace an existing release tag.

If an optional tool is unavailable, its scope is recorded as `not_available`; it cannot be counted as passing evidence. A release must not be described as STA-closed, formally exhaustive, or signoff-quality beyond the exact executed scope.
