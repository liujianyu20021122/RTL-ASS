# Installation and removal

## Requirements

- Python 3.11 or 3.12.
- Codex for the skill workflow.
- Only the open-source tools needed by the requested evidence: Verilator, Icarus Verilog, Yosys, OpenSTA, and GTKWave's `fst2vcd` are independently optional.

## Install the helper

From a release download:

```bash
python3 -m venv .venv
.venv/bin/pip install --no-deps rtl_ass-1.0.0-py3-none-any.whl
.venv/bin/rtl-ass --version
.venv/bin/rtl-ass doctor
```

From source:

```bash
python3 -m pip install --no-deps .
rtl-ass --version
```

## Install the Codex skill

Extract `rtl-ass-skill-1.0.0.zip`. Copy the archive's `rtl-ass` directory into the configured Codex skills directory, preserving `SKILL.md`, `agents/`, `references/`, and `scripts/`. Keep the helper wheel installed so a standalone skill archive can call `rtl-ass`.

For repository development, Codex can use `.agents/skills/rtl-ass/` directly and its launcher imports `src/rtl_ass` from the checkout.

## Verify integrity

```bash
(cd path/to/downloaded/assets && sha256sum --check SHA256SUMS)
python3 -m pip install --no-deps rtl_ass-1.0.0-py3-none-any.whl
rtl-ass --version
```

Compare release checksums with the signed-in GitHub release page. `rtl-ass-sbom.spdx.json` lists the first-party release package and file checksums.

## Remove

```bash
python3 -m pip uninstall rtl-ass
```

Then remove only the installed `rtl-ass` skill directory from the configured Codex skills directory. Knowledge databases and artifacts are user data and are intentionally not deleted; remove those explicit paths separately if no longer needed.
