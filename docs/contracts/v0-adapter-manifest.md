# v0 adapter manifests

An adapter manifest declares identity/version, supported contracts, filesystem,
network, credential, mutation, and provider-output read capabilities, input and
output schema references, and determinism. It explicitly states that record
contents cannot authorize execution. Adapter receipts are machine-readable and
do not imply execution, mutation, credentials, or approval.

The intended adapter classes are scanner, resolver, vault, transport, indexer,
policy, and context-exporter. V0 implements only machinery exercised by the
first vertical slice; class names are descriptive categories, not discovery or
loading hooks.

`adapter-manifest/v1` remains the permissive legacy declaration contract so
previously retained opaque extension values remain readable. It does not
interpret or negotiate those values. `adapter-manifest/v2` adds the strict,
globally identified `{version, required, value}` extension carrier: unknown
optional values are preserved, while malformed or unsupported required values
fail closed. Both versions are declarations, not permission grants. Filesystem,
network, credentials, and mutation fields describe requirements that an
external orchestrator must separately authorize. Schema-valid records and
extension values cannot start an adapter, TraceMap, or another tool. Validation
does not import, install, discover, load, or execute adapter code.

The TraceMap binding manifest is read-only, network-free, credential-free, and
explicitly declares `trace-map-local-output` read capability. TraceMap output
resolution and adapter invocation are authorized outside portable records. The
manifest preserves provider schema references as provider contracts; it does
not promote them into core schemas or reinterpret provider evidence.

Validation applies the packaged public schema before emitting a receipt. A
schema-valid manifest emits `succeeded`. Invalid declarations emit `failed`
with a stable diagnostic code, validator detail code, and JSON path. Invalid
or unavailable adapter identities use `adapter://unknown/unknown` in the
failure receipt rather than echoing an unusable identity. Diagnostics never
echo manifest values, local paths, credentials, or provider content.
Unavailable or invalid packaged schemas remain typed runtime failures; they
are not misreported as defects in the caller's manifest.

The checked synthetic fixture proves one independent reference-adapter success
receipt and one authority-boundary failure receipt. Its v2 conformance receipt
also binds four ordered extension cases and derives preservation from the
observed carrier. It schema-validates the TraceMap manifest used by the first
vertical slice. V0 deliberately omits plugin discovery, dynamic remote loading,
a marketplace, and a generalized isolation runtime.
