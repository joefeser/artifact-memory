# 0026: Exclude-superseded search filter

## Status

Accepted, 2026-08-27, for issue
<https://github.com/joefeser/artifact-memory/issues/108>.

## Context

The corrected retrieval audit of `153f2843` (finding F5, with M6 adjacent)
showed that superseded records searched without lifecycle marking or filter,
so a superseded record remained a first-class search hit with no surfaced
lifecycle state. The independent second opinion measured that naive changes
to default search output break the pinned scan-projection fixture, the
vertical slice, and both WITS conformance tests, so the filter had to be
additive.

## Decision

- Both `search` and `search-receipt` accept `--exclude-superseded`, which
  drops matches whose `lifecycle` column is `superseded`. The default keeps
  superseded records as first-class hits; the flag is the caller's opt-in.
- The filter runs inside the same gated read transaction as the match, on the
  same verified snapshot, and composes with both query grammars.
- Search receipts record `exclude_superseded` (boolean, optional in the v1
  schema, always set on newly issued receipts) beside `query_mode` and the
  query digest, so every result-affecting parameter is bound and filtered
  results are replayable.
- This is a read-time lifecycle filter, not revocation: revocation
  suppression remains a projection-build input, and making it reachable from
  the CLI is separate work.

## Compatibility

- Additive: defaulted keyword argument, CLI flag, optional receipt field; no
  schema, output, or fixture shape changes. Default search behavior is
  unchanged.

## Authority and limitations

The filter is informational result shaping over restricted lexical meaning.
It does not interpret the supersession relationship, prove which record
superseded which, revoke anything, or grant execution, mutation, disclosure,
or approval authority. Other non-current lifecycles (draft, rejected, sealed)
are unaffected.

## Evidence

- GitHub issue: <https://github.com/joefeser/artifact-memory/issues/108>
- Contract: `docs/contracts/v0-filesystem-and-projections.md`
- Receipt schema: `artifact_memory/schemas/core/search-receipt.v1.schema.json`
  (`exclude_superseded`)
- Slice: `artifact_memory/search_supersession_slice.py`, replayed by
  `python3 scripts/run_search_supersession_slice.py --check` against
  `fixtures/synthetic/search-supersession/v1/expected-receipt.json`
- Unit fixtures: `tests/test_projection.py`
  (`test_search_exclude_superseded_filters_lifecycle_at_read_time`) and
  `tests/test_cli.py` (`test_search_exclude_superseded_through_cli`)
