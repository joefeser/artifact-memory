# Synthetic coordination fixtures

The top-level JSON files are wholly synthetic TaskPacket and AccessLabel
records used by the AM-2 acceptance command:

```sh
artifact-memory records validate fixtures/coordination/*.json
```

The `invalid/` directory contains synthetic negative vectors and is excluded
from that glob. WorkReceipt bodies are deliberately not checked in here: the
coordination contract makes the complete receipt, including its writer,
machine, and token-note fields, vault-only. Tests construct an ephemeral
synthetic WorkReceipt in a temporary directory to exercise the public schema,
CLI, and exact-revision bindings without creating a repository fixture.

All record text is informational and grants no execution, disclosure,
credential, spending, deployment, approval, or merge authority.
