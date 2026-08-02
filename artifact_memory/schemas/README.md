# Schemas

This directory will contain versioned, implementation-neutral JSON Schemas.

Each schema requires:

- a stable schema identifier and explicit version;
- valid and invalid synthetic examples;
- compatibility and unknown-field behavior;
- sensitivity and authority implications;
- deterministic conformance tests.

No schema is normative merely because an implementation can parse it. The
normative canonical serialization and exact-content rules are in
`docs/contracts/v0-canonical-records.md` and
`docs/contracts/v0-content-objects.md`. Normative scan completeness behavior is
in `docs/contracts/v0-scan-policy-and-receipts.md`; their checked vectors remain
runtime-neutral even though the first runner is Python.

Normative storage endpoint, logical reference, endpoint discovery, and location
observation behavior is in `docs/contracts/v0-storage-endpoints-and-locations.md`.
Machine-local resolver configuration is explicitly non-portable.
