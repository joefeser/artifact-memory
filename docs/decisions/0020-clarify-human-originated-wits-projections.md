# 0020: Clarify human-originated WITS projections

## Status

Accepted, 2026-08-11, for issue #92. This decision supersedes only the meaning-
ownership wording in Decision 0007; its opaque provider boundary, licensing,
and authority restrictions remain in force.

## Context

Released WITS adapter schemas use the projection kind `owner-meaning`, and
earlier prose said that WITS owns owner meaning. That wording can be read as
assigning origination or adjudication of product meaning to software. The
authorized human originates product meaning. WITS authenticates applicable
authority, admits the human decision, and governs its recorded lifecycle.
Artifact Memory preserves exact portable revisions, relationships, lifecycle
observations, and receipts without deciding what the product should mean.

The identifier already appears in strict v1 and v2 schemas and in released
synthetic fixtures. Renaming it in place would break compatible readers and
could change projection identities or fixture digests.

## Decision

- Freeze `owner-meaning` as a legacy v1/v2 wire identifier.
- Interpret it normatively as an opaque projection of human-originated meaning
  admitted by WITS. It does not claim WITS originated, owns, or independently
  approved the meaning.
- Preserve the released schemas, fixture payloads, projection identities, and
  receipt digests exactly. Historical wording remains visible but is marked
  superseded by this decision.
- Reserve `admitted-owner-decision` as the preferred successor identifier for
  the next material, explicitly negotiated WITS adapter-contract version. It
  is not supported by v1 or v2, and no silent translation is allowed.
- Keep the Artifact Memory core protocol unchanged. This correction does not
  justify a core schema version.

## Authority boundary

A projection is informational. Admission records a WITS process outcome bound
to exact inputs; it does not itself prove that the human authority was valid.
Artifact Memory does not infer, approve, adjudicate, or execute the decision.
No projection kind grants task, decision, disclosure, declassification,
routing, mutation, credential, spending, deployment, merge, or execution
authority.

## Consequences

Existing consumers continue to accept and replay `owner-meaning`. New public
documentation has precise human/WITS/Artifact Memory ownership language. A
future successor requires a separately reviewed versioned contract and
conformance fixture; merely recognizing this ADR is not negotiation support.

## Evidence

- GitHub issue: <https://github.com/joefeser/artifact-memory/issues/92>
- Contract: `docs/contracts/v0-wits-adapter-boundary.md`
- Compatibility tests: `tests/test_wits_adapter.py`
- Historical fixture: `fixtures/synthetic/wits/v1/`
