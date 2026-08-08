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

`exchange-envelope.v2.schema.json`, `admission-receipt.v2.schema.json`,
`exchange-conformance-vectors.v1.schema.json`, and
`exchange-conformance-receipt.v1.schema.json` define the issue #22 bounded
bundle manifest, six admission outcomes, replay behavior, and checked
contradictory/replayed vectors. Exchange grants no authority and never carries
bearer credentials.

`independent-exchange-vectors.v1.schema.json` and
`independent-exchange-conformance-receipt.v1.schema.json` define the issue #23
reference-sender to stdlib-only receiver fixture. The receipt binds compatible
v2 admission receipts, optional preservation, required fail-closed behavior,
and the separately authorized artifact-retrieval boundary.

`adapter-manifest.v1.schema.json` preserves the legacy opaque-extension reader;
`adapter-manifest.v2.schema.json` defines strict optional/required extension
negotiation. `adapter-receipt.v1.schema.json` and the versioned
`adapter-manifest-conformance-receipt` schemas define typed success/failure
receipts and checked synthetic evidence for issue #11. These schemas grant no
execution authority or loading behavior.

`tracemap-adapter-receipt.v1.schema.json` and
`tracemap-failure-conformance-receipt.v1.schema.json` define the issue #39
provider-preserving adapter outcome surface and its checked public-safe failure
matrix. Provider schemas remain TraceMap-owned contracts.

`vault-intake-vector.v1.schema.json`, `vault-intake-receipt.v1.schema.json`, and
`vault-intake-conformance-receipt.v1.schema.json` define the issue #18 private
filesystem intake outcomes and checked public-safe synthetic evidence.

`release-manifest.v2.schema.json`,
`release-candidate-preparation-receipt.v1.schema.json`, and
`release-candidate-verification-receipt.v1.schema.json`,
`release-candidate-verification-receipt.v2.schema.json` separate deterministic
asset preparation, pending owner signature, verified signed-tag evidence, and
publication authority. V1 remains readable as historical tag/manifest evidence;
v2 adds mandatory staged-asset replay and checksum evidence. Synthetic examples
never represent a real key or tag.
