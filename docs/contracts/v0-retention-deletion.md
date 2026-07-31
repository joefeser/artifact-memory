# v0 retention, deletion, redaction, and tombstones

Removal receipts are scoped evidence, not global or cryptographic erasure
claims. The reference layer creates policies, observations, receipts, and
non-sensitive tombstones. It does not delete bytes, purge backups, rewrite Git
history, or mutate a vault. Every destructive operation requires separate
owner or legal authorization outside these informational contracts.

The strict #36 fields are published as `retention-policy/v2`,
`deletion-receipt/v2`, `tombstone/v2`, and `knowledge-record/v2` for the
`redacted-from` relationship. Their v1 schemas remain unchanged so
previously valid records keep their original meaning. There is no implicit
v1-to-v2 reinterpretation: producers create a new v2 object after an explicit
policy decision, and v1-only readers reject the unknown v2 `schema_id`.

## Lifecycle distinctions

- A draft may be discarded before admission. No accepted-record identity or
  supersession claim is created for a discarded draft.
- An accepted record remains part of history when superseded. Its replacement
  identifies the relationship; supersession is not deletion.
- A redacted derivative receives its own record identity and records a
  `redacted-from` relationship to the source identifier. It must not copy the
  removed payload into provenance, a tombstone, or a generated view.
- A tombstone retains only identifiers, a categorical reason and content
  status, a scoped deletion receipt reference, time, and an optional successor.
  `sensitive_payload_retained: false` is normative.

Artifact bytes and the minimum lifecycle receipt are separate objects. Removing
bytes from an authorized scope does not require removing the non-sensitive
receipt that explains what was attempted and where. A digest with zero
currently verified retrievable locations is still an identity; it is not proof
that no copy exists.

## Scope and outcome

Each deletion receipt applies to exactly one scope: active vault, generated
index, managed backup, Git history, named endpoint, or unknown replica scope.
Endpoint outcomes name the portable logical endpoint; a backup generation also
names the generation. Hostnames, addresses, mount points, drive letters, and
UNC paths are observations or local configuration and never durable identity.

The v0 outcome vocabulary is:

- `requested`, `attempted`, `removed-observed`,
  `verified-absent-at-endpoint`, `retained-until-expiry`, `not-authorized`,
  `endpoint-unavailable`, `scope-unknown`, `failed`, and
  `partially-complete`.

`removed-observed` records an observed removal event.
`verified-absent-at-endpoint` additionally records a verification against the
named endpoint. Neither says anything about another endpoint or replica.
Location observations use `absent`, `removal-observed`, `unavailable`, and
`verified-absent-at-endpoint` for the same endpoint-scoped distinction.

Retrievability summaries are content-specific and current-state projections.
Each evaluation accepts observations for exactly one `content_ref`, selects the
newest observation for each endpoint-relative-path location, and rejects
conflicting states tied at the newest observation instant.

Managed backup retention keeps the aggregate deletion result
`partially-complete` while any named generation retains bytes. A later purge
receipt can prove only the named endpoint and generation. Unknown and unmanaged
replicas remain `scope-unknown`; inability to enumerate them stays visible.
Owner and legal holds defer destructive work and must not be represented as a
completed removal. Git-history rewriting has its own explicit authorization
and coordination boundary.

Generated NDJSON, SQLite, search, and relationship indexes are disposable. A
post-deletion rebuild must use the current authorized canonical set and prove
that removed content is absent. The synthetic #36 fixture exercises accidental
ingestion, a redacted derivative, deferred backup expiry, owner-approved
deletion, and this rebuild invariant without touching any real endpoint. Its
fixture persists the validated deletion receipts and tombstones, and its
aggregate receipt binds their canonical digest. A reader can independently
inspect every endpoint, generation, evidence reference, and limitation rather
than receiving dangling hashes.
