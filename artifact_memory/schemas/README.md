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

Normative artifact/version identity and lineage behavior is in
`docs/contracts/v0-artifacts-versions-and-lineage.md`.

Normative storage endpoint, logical reference, endpoint discovery, and location
observation behavior is in `docs/contracts/v0-storage-endpoints-and-locations.md`.
Machine-local resolver configuration is explicitly non-portable.

Normative aggregate synthetic fixture manifests, runner-neutral expected
results, and representative class coverage are in
`docs/contracts/v0-synthetic-conformance-fixtures.md`.

`manifest-conformance-vectors.v1.schema.json` and
`manifest-conformance-receipt.v1.schema.json` define the runner-neutral issue
#6 fixture and its checked evidence envelope. The fixture corpus remains under
`fixtures/synthetic/manifests/v1/` rather than inside the installed package.

`extension-bundle.v1.schema.json` and
`extension-conformance-receipt.v1.schema.json` define the deliberately narrow
issue #10 optional/required extension surface and its checked evidence.
