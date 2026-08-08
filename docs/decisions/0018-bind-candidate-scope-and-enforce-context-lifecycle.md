# 0018: Bind candidate scope and enforce context lifecycle

## Status

Accepted, 2026-08-08, for issue #83.

## Context

Candidate v1 cannot add required scope or uncertainty fields without changing
existing candidate identities and breaking strict validators. Context-pack v2
and v3 cannot receipt lifecycle exclusions separately from freshness without
breaking their closed schemas. Relying on callers to invoke `current_records()`
allowed draft or superseded records to reach context export.

## Considered options

1. Extend the strict v1/v2/v3 schemas in place. Rejected because it would break
   existing identities and strict readers.
2. Require every caller to pre-filter with `current_records()`. Rejected because
   the security property would remain optional at the export boundary.
3. Add negotiated candidate/receipt v2 and context-pack v4 contracts. Chosen
   because it preserves released contracts and makes exclusions explicit.

## Decision

- Freeze candidate and admission-receipt v1 for exact replay.
- Add candidate v2 with explicit canonical namespace, bounded input references,
  validated non-location provenance references, unique source identities, and
  optional first-class uncertainty.
- Add admission-receipt v2 with exact immutable predecessor transitions for
  accepted `supersedes` relationships.
- Make `export_context` enforce accepted-or-sealed lifecycle eligibility before
  freshness, regardless of caller selection.
- Freeze context-pack v2/v3. Require explicit negotiation of context-pack v4
  whenever lifecycle exclusion must be receipted.
- In v4, report only aggregate lifecycle counts and identify record/evidence
  selection inputs as caller-supplied and unauthenticated.
- Preserve the released Codex-history conformance v1 bytes and publish its
  lifecycle-corrected synthetic proof under conformance receipt v2.

## Consequences

Existing v1 candidate identities and v2/v3 context identities remain
replayable. New v2 candidate identities intentionally bind scope and
uncertainty. A caller that supplies lifecycle-ineligible records without
negotiating v4 receives a typed failure instead of a misleading old-version
receipt. Candidate admission and context export still create no authority;
WITS continues to own meaning, approval, and conflict resolution.

Security improves because lifecycle-ineligible records cannot be exported even
when caller-selected and marked fresh. Compatibility is explicit: released
schemas are unchanged, new receipts require negotiation, and no downgrade is
performed.

## Links and evidence

- GitHub issue: <https://github.com/joefeser/artifact-memory/issues/83>
- Contract: `docs/contracts/v0-record-evolution.md`
- Contract: `docs/contracts/v0-context-pack.md`
- Synthetic proof: `fixtures/synthetic/record-evolution/v2/`
