# v0 minimum record, content, and filesystem contracts

Status: normative minimum for the first executable slice
Date: 2026-07-30

This packet defines the smallest contract surface needed to admit one
synthetic record, identify its exact bytes, and report an honest filesystem
observation. It covers issues #4, #5, #7, #8, and #9; it does not define a
complete manifest, index, adapter, retention policy, or authenticity protocol.

## Identity boundaries

- A knowledge record describes meaning and references; it does not identify
  bytes or a location by itself.
- An artifact is a durable logical thing. An artifact version is one immutable
  revision of that thing.
- A content object is exact bytes identified by a named digest and byte size.
- A storage endpoint is logical. A location observation records what was seen
  at that endpoint and relative path at a time. Absolute paths, mount points,
  hostnames, and bearer URLs are not durable identifiers.
- A scan receipt describes the scope and completeness of an observation. It is
  not proof that omitted or unreadable entries do not exist.

The JSON Schemas in `artifact_memory/schemas/core/` are normative for field names, types,
required fields, and closed top-level vocabularies. Unknown top-level fields
are rejected. Optional namespaced extensions belong under `extensions` and are
preserved without interpretation. Required extensions fail closed under the
completed v0 extension contract.

## Canonical serialization and identifiers

The complete numeric, encoding, revision, and supersession rules are normative
in `v0-canonical-records.md`. A canonical record's digest is SHA-256 over its
canonical bytes and is represented as `sha-256:<lowercase-hex>`. Timestamps are
metadata and never identity inputs unless a later contract explicitly says so.
The schemas do not authorize a resolver, execution, mutation, declassification,
or trust decision.

## Honest scan outcomes

The complete normative scan policy, exclusion, attempt, and receipt rules are
in `v0-scan-policy-and-receipts.md`.

The normative logical artifact, immutable version, role, content-binding,
lineage, provenance, and supersession rules are in
`v0-artifacts-versions-and-lineage.md`.

`complete` means the declared scope was scanned and every in-scope entry was
accounted for. `partial`, `failed`, and `cancelled` are explicit outcomes.
Unreadable entries, exclusions, unsupported entry kinds, and collisions are
reported in the receipt; they are not silently converted into absence.

The synthetic conformance fixtures demonstrate canonical record/content
behavior, explicit scan completeness outcomes, and rejection of a
machine-local absolute path in portable records.
