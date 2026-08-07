# Quickstart

Artifact Memory v0 is a provider-free Python reference runtime. It is not a
service and it does not require a vault, credentials, or network access.

From a clean clone:

```shell
python3 -m pip install --no-deps .
artifact-memory version --json
python3 -m artifact_memory version --json
scripts/validate_contracts.sh
scripts/run_conformance.sh
python3 -m artifact_memory validate fixtures/synthetic/contracts/v0-valid-record.json --json
```

The repository contains synthetic fixtures only. A generated index or context
pack is a derived view; it is not a replacement for canonical records.

The v0 support boundary is documented in the contract files and receipts.
Unsupported filesystem semantics, unverified authenticity, unknown required
extensions, and authority-bearing adapter requests fail closed or remain
explicit outcomes.
