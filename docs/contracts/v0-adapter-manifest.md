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

`adapter-manifest/v1` is a declaration, not a permission grant. Filesystem,
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

The checked synthetic fixture proves one independent reference-adapter success
receipt and one authority-boundary failure receipt. It also schema-validates
the TraceMap manifest used by the first vertical slice. V0 deliberately omits
plugin discovery, dynamic remote loading, a marketplace, and a generalized
isolation runtime.
