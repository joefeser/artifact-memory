# v0 TraceMap evidence binding

The issue #39 adapter registers and binds an existing TraceMap evidence packet
without running TraceMap, interpreting its rule semantics, or importing
provider schemas into Artifact Memory core. The initial provider contract is
anchored to TraceMap commit
`9a252f12f781ae2a0aab52b5faa53601440a2a3b`.

The adapter snapshots the five required packet artifacts, rejects links and
SQLite sidecars, validates repository and commit provenance, checks facts and
the generated SQLite index for parity, and binds selected opaque provider
record identities to one Artifact Memory artifact-version reference. TraceMap
continues to own facts, rules, evidence tiers, analysis coverage, and known
gaps. Filesystem completeness and analysis completeness remain separate facts.

For valid input, the binding outcome is `complete` or
`partial-evidence-admitted`. Known gaps force the partial outcome. Unsigned
evidence remains labeled `integrity-verified / issuer-unverified`; provider
provenance does not establish authenticity or trust.

The receipted entry point covers this complete declared outcome surface:

- `required-artifact-missing`;
- `schema-unsupported`;
- `trace-output-invalid`;
- `digest-mismatch`;
- `repository-binding-mismatch`;
- `commit-binding-mismatch`;
- `source-version-unavailable`;
- `rule-catalog-unavailable`;
- `configuration-identity-unavailable`;
- `unsafe-provenance-rejected`;
- `provider-record-not-found`;
- `partial-evidence-admitted`;
- `adapter-failed`;
- `complete`.

Failure receipts contain only the typed outcome. They do not echo exception
text, protected content, provider values, or local paths. Unexpected faults
collapse to `adapter-failed`. A failed receipt emits no binding and does not
claim that packet integrity was assessed.

The additive receipted API exposes the specialized configuration and rule
catalog outcomes. The original binding API preserves its v0 compatibility
behavior by reporting either malformed identity as `trace-output-invalid`.
Receipts normally carry `validation_state: validated`. If the packaged receipt
schema cannot be loaded or executed, the boundary still returns a schema-shaped
`adapter-failed` receipt marked `not-validated-runtime-failure`; it does not
return a binding or pretend validation succeeded.

Configuration identity is required. Rule-catalog identity remains optional;
omission is valid, while a supplied value that is not an exact SHA-256 identity
returns `rule-catalog-unavailable` rather than silently weakening provenance.

The checked synthetic failure matrix exercises every outcome independently.
Its closed case object binds each normative case name to the same expected and
observed outcome. It intentionally omits per-case receipt and binding IDs,
because successful binding identities include the provider's replaceable
SQLite artifact bytes and are not portable checked-fixture values. Each
individual runtime receipt is still schema-validated before the aggregate is
produced.
The separate exact-anchor vertical slice proves successful source validation,
registration, evidence binding, claim projection, bounded context export,
encrypted backup, isolated restore, index rebuild, and context revalidation.
Neither fixture grants execution, routing, disclosure, approval, mutation, or
provider-invocation authority.
