# RTL-ASS starter knowledge pack

This directory is first-party Apache-2.0 material. It demonstrates the portable pack boundary with separately indexed RTL, testbench, assertion harness, design contract, and verification guidance.

The pack is deliberately small. It is evidence-backed reference material for Codex to inspect and adapt; it is not a code generator and is never promoted automatically when imported.

Validate and import it with:

```bash
rtl-ass kb pack-validate library/starter/pack.json
rtl-ass kb init --db .rtl-ass/knowledge.db --actor local-user
rtl-ass kb import-pack library/starter/pack.json --db .rtl-ass/knowledge.db \
  --namespace builtin:starter --actor local-user
```
