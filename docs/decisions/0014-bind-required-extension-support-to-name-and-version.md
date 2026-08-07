# ADR 0014: Bind required extension support to namespace and version

- Status: Accepted
- Date: 2026-08-02
- Issues: #10, #11
- Discussion: #31

## Context

Artifact Memory must preserve unfamiliar domain data without allowing it to
fragment core interoperability or smuggle executable authority. Treating
support for an extension namespace as support for every version would let a
reader accept required semantics it does not understand.

## Decision

V0 extension declarations remain nested under one globally namespaced HTTPS
identifier and contain an explicit version, required flag, and object value.
Unknown optional declarations round-trip opaquely. Required declarations are
accepted only when the reader explicitly supports the exact `(identifier,
version)` pair; otherwise they fail closed.

Namespace containment means extension value keys never replace core identity,
digest, sensitivity, schema, or authority fields. Applying a declaration over
a different existing value at the same identifier is a conflict, not an
implicit update. Extension data never authorizes adapter execution.

## Alternatives considered

- Namespace-only required support was rejected because versions can change
  normative meaning.
- Flattening extension fields into core records was rejected because name
  collisions could redefine core semantics.
- A registry, discovery service, marketplace, inheritance model, and remote
  executable loading were deferred because the first slice needs none of them.

## Consequences

The synthetic issue #10 fixture proves one optional round trip, one unknown
required rejection, explicit exact-version support, unchanged core fields, and
a non-authority boundary. Issue #11 may use this data contract but owns adapter
capabilities and receipts separately.
