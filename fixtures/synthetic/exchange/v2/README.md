# Synthetic exchange v2 conformance vectors

These newly authored public-safe records exercise the six issue #22 admission
outcomes. The contradictory case changes only a synthetic declared digest. The
replay case uses an in-memory synthetic ledger and proves that repeated replay
returns the same deterministic `duplicate` receipt.

Artifact references are informational. The fixture never retrieves bytes,
contains no bearer credential, and grants no execution, disclosure, spending,
routing, credential, deployment, merge, or mutation authority.
