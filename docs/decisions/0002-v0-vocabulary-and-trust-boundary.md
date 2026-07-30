# Decision 0002: v0 vocabulary and trust boundary

Status: accepted
Date: 2026-07-30
Linked issues: #2, #3, #1

## Context

Artifact Memory must preserve meaning without confusing it with bytes,
locations, generated views, transport, or authority. The first executable
slice needs a small vocabulary that independent implementations can use before
the full filesystem and adapter surface exists.

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

Lifecycle states are explicit: `draft`, `accepted`, `sealed`, `superseded`,
and `rejected`. A draft may be revised; a sealed record is immutable; a
superseded record remains evidence of its former state; a rejected record is
retained only when policy requires an auditable outcome.

## Trust and privacy boundary

The public repository may contain protocol contracts, reference code, synthetic
fixtures, and sanitized receipts. A private vault may contain real records and
artifact bytes. A valid JSON record or digest proves structure or integrity
only; it does not prove the claim is true, the sender is trusted, the receiver
is authorized, or the referenced bytes may be disclosed.

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

## Consequences

Later schema, manifest, authenticity, extension, and adapter decisions must
preserve these separations. The narrow vocabulary allows the first vertical
slice to expose implementation mistakes without requiring v0 to pretend that
all platform filesystem semantics are equivalent.
