# Decision 0002: v0 vocabulary and trust boundary

Status: accepted
Date: 2026-07-30
Linked issues: #2, #3, #1
Supersedes: none

## Context

Artifact Memory must preserve meaning without confusing it with bytes,
locations, generated views, transport, or authority. The first executable
slice needs a small vocabulary that independent implementations can use before
the full filesystem and adapter surface exists.

## Considered options

1. Use paths, filenames, or content digests as artifact identity. Rejected
   because locations change and identical bytes can represent different
   semantic artifacts or versions.
2. Combine knowledge, artifacts, content, locations, and receipts into one
   record type. Rejected because it would hide provenance and make generated
   projections look canonical.
3. Treat exchanged records or receipts as operational authority. Rejected
   because evidence and transport cannot safely grant execution, disclosure,
   mutation, or approval.
4. Keep the vocabulary and authority boundaries explicit and non-overlapping.
   Chosen because independent implementations can validate each claim without
   silently inheriting authority from another layer.

## Decision

The v0 terms are intentionally non-overlapping:

| Term | Definition | Must not be confused with |
| --- | --- | --- |
| Knowledge record | Canonical structured text describing meaning, claims, provenance, sensitivity, and relationships. | An artifact byte or generated index row |
| Artifact | Stable semantic identity for a meaningful thing. | A filename, path, content hash, or version |
| Artifact version | Immutable revision of an artifact, such as an original, derivative, redaction, or release. | A mutable record edit |
| Content object | Exact bytes identified by a named digest and size. | The thing those bytes mean |
| Storage endpoint | Logical storage authority that can be resolved locally. | A mount point, drive letter, hostname, or provider URL |
| Location observation | Time-bound evidence that content was observed at a logical endpoint location. | Durable identity or proof of custody |
| Manifest | Deterministic inventory of a bounded supported tree or package. | A container-file digest or a complete filesystem claim |
| Scan receipt | Evidence of a scan policy, scope, completeness, exclusions, warnings, failures, and resulting manifest. | A claim that every entry was readable |
| Exchange envelope | Bounded transport container for records, references, integrity data, and handling instructions. | Execution or disclosure authority |
| Receipt | An evidence record for an operation or outcome, including its limits and provenance. | Approval, authorization, or truth of an asserted claim |

Canonical records are versioned JSON text. NDJSON, SQLite, HTML, graphs, search
indexes, and context packs are generated projections and never the only copy of
durable knowledge.

Lifecycle states apply to versioned knowledge and protocol records, not to
immutable operation receipts. Only `draft` may be edited in place. The allowed
v0 transitions are:

| Current state | Allowed next state |
| --- | --- |
| `draft` | `accepted` or `rejected` |
| `accepted` | `sealed` or `superseded` |
| `sealed` | `superseded` |
| `superseded` | none |
| `rejected` | none |

Every transition out of `draft` creates durable history rather than replacing
the prior accepted or sealed record. A superseding record names what it
supersedes; rejection does not authorize a later state transition. Individual
record schemas decide whether a lifecycle field is required. Until those
schemas exist, consumers must not infer edit or transition authority from a
missing lifecycle field.

## Rationale

Separate identities keep semantic meaning stable while content and storage
locations change. Explicit lifecycle, provenance, and non-authority rules also
let implementations report incomplete or unverified evidence without
upgrading it into a trusted claim.

## Security consequences

The public repository may contain protocol contracts, reference code,
synthetic fixtures, and receipts newly authored from public-safe synthetic
inputs. Sanitizing or redacting a private operational receipt does not make it
publishable. A private vault may contain real records and artifact bytes. A
valid JSON record or digest proves structure or integrity only; it does not
prove the claim is true, the sender is trusted, the receiver is authorized, or
the referenced bytes may be disclosed.

Knowledge exchange never grants execution, mutation, spending, deployment,
credential use, declassification, or approval authority. An adapter must be
authorized independently by its receiving system.

## Failure behavior and nonclaims

- Unknown required behavior fails closed; unknown optional data is preserved
  without interpretation.
- Incomplete scans, unreadable entries, unsupported semantics, unavailable
  endpoints, and unverified content remain explicit outcomes.
- A path, mount point, provider URL, filename, or generated row is not durable
  identity.
- A receipt records what was attempted and observed; it does not upgrade an
  unsupported or unverified claim.

## Synthetic separation example

```json
{
  "artifact": "artifact://synthetic/example/ART-0001",
  "version": "artifact://synthetic/example/ART-0001/versions/1",
  "content": {"algorithm": "sha-256", "digest": "SYNTHETIC-DIGEST", "size": 12},
  "location_observation": {"endpoint": "endpoint://synthetic/alpha", "relative_path": "notes/example.txt"},
  "meaning": {"kind": "synthetic-note", "claim": "This is fixture text only."}
}
```

The example deliberately keeps meaning, artifact/version identity, exact
content, and observed location separate. It grants no retrieval or execution
authority.

## Compatibility consequences

Later schema, manifest, authenticity, extension, and adapter decisions must
preserve these separations. The narrow vocabulary allows the first vertical
slice to expose implementation mistakes without requiring v0 to pretend that
all platform filesystem semantics are equivalent. Implementations may add
extensions, but unknown required extensions fail closed and unknown optional
extensions remain opaque; future decisions that change these identities or
authority boundaries must supersede this record explicitly.
