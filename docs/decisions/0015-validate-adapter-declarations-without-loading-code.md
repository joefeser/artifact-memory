# ADR 0015: Validate adapter declarations without loading code

## Status

Accepted for v0.

## Context

The first vertical slice already exercises a TraceMap evidence-binding adapter
and materially separate readers. Issue #11 needs a common declaration for
identity, supported contracts, capability requirements, schemas, determinism,
and receipts. A manifest must not become a hidden plugin loader or authority
envelope.

The initial runtime checked only field presence and the execution-authority
flag. It could therefore emit successful receipts for schema-invalid adapter
identities, capabilities, determinism values, and unknown fields.

## Decision

The v0 runtime validates `adapter-manifest/v1` against the packaged public
schema before emitting a success receipt. Invalid manifests emit deterministic
failure receipts with typed, path-aware diagnostics that do not echo input
values. Invalid adapter identities are represented by the portable fallback
`adapter://unknown/unknown`.

Manifest capability fields describe requirements only. Authorization remains
external to records and manifests. Validation performs no discovery,
installation, import, dynamic loading, network access, credential use,
filesystem access, mutation, or execution.

The synthetic conformance fixture checks one success and one
authority-boundary failure. The existing TraceMap manifest supplies evidence
for the first real local-provider-output read capability.

## Consequences

- Independent implementations can validate the same public declaration before
  deciding whether a separately authorized adapter may run.
- Receipts are safe to exchange as outcomes but do not grant authority.
- Scanner, resolver, vault, transport, indexer, policy, and context-exporter
  categories remain documentation until a vertical slice exercises them.
- Plugin discovery, remote loading, marketplaces, and generalized isolation
  remain out of scope.
