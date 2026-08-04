# ADR 0003: Reference runtime and CLI boundaries

Status: accepted for v0 reference implementation
Date: 2026-07-30

## Decision

Use Python 3.11+ from the standard library for the v0 reference runtime. The
protocol remains runtime-neutral: JSON Schemas and synthetic fixtures are
portable text and do not require Python to consume. Python is an implementation
choice for the first executable seam, not a wire or storage requirement.

The supported v0 surface is deliberately small:

- `artifact-memory version` reports implementation and contract versions;
- `artifact-memory inspect RECORD` reports the record schema and top-level
  field names without echoing local paths or record contents;
- `artifact-memory validate RECORD` validates JSON syntax, duplicate-key
  rejection, the selected v0 schema, the supported JSON Schema keywords, and
  schema-specific semantic rules exposed by the reference implementation. For
  `release-manifest/v1` and `/v2`, acceptance also requires
  `validate_release_manifest()` to pass. A legacy v2 release fingerprint can
  remain schema-readable for compatibility while `validate` rejects it with
  exit status 2 and `release-fingerprint-migration-required`; schema shape
  alone is not evidence that a manifest is releasable. `inspect` is the
  non-validating metadata surface for callers that only need schema and field
  names.

The validator fails closed for an unknown schema identifier, reports
unsupported schema constructs as a typed outcome, and returns exit status 2
for schema or supported semantic rejection. It does not resolve files, execute
adapters, infer authority, or make authenticity claims. Generated indexes and
private-vault configuration are outside this package.

The single canonical schema tree lives under `artifact_memory/schemas/` so the
same versioned text is available in a source checkout and as installed package
resources. The package does not maintain a second generated schema copy.

## Alternatives considered

- Node.js: strong ecosystem support, but would add a package-manager/runtime
  dependency before the protocol seam is proven.
- Rust or Go: good distribution properties, but higher contributor and fixture
  friction for the contract-first v0.
- Python with third-party JSON Schema libraries: useful later, but the first
  CLI must remain runnable in a clean standard-library environment.

## Platform policy

Python 3.11+ is supported on macOS, Windows, and Linux. The CLI uses UTF-8,
`pathlib`, and standard streams; it does not depend on path separators,
drive-letter syntax, mount points, hostnames, environment-specific resolver
files, or a user home directory. Cross-platform filesystem semantics remain
future contract work.

## Package map

```text
artifact_memory/                 reference runtime and CLI
artifact_memory/schemas/         runtime-neutral versioned schemas
fixtures/synthetic/              public synthetic conformance inputs
docs/contracts/                  normative contract notes and vectors
docs/decisions/                  consequential implementation decisions
adapters/                        declared adapter machinery
generated/                       intentionally absent; views are replaceable
```
