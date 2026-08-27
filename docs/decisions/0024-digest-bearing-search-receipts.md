# 0024: Digest-bearing search receipts

## Status

Accepted, 2026-08-27, for issue
<https://github.com/joefeser/artifact-memory/issues/106>.

## Context

The corrected retrieval audit of `153f2843` (finding F1, confirmed by the
independent second opinion) showed that search, related, and provenance
receipts omitted `source_record_set_digest`, so query evidence was
unpinnable, and the digest was unreachable from the CLI. WITS 1151 closeout
requires digest binding — required, not narrowed — but gated on the M0
integrity gate (decision 0023) so a receipt cannot vouch for an index whose
inverted index was never verified. The second
opinion measured empirically that changing existing output shapes breaks the
pinned scan-projection fixture, the vertical slice, and both WITS
conformance tests; an additive implementation passed them all.

## Decision

- Add a `search_receipt` library surface and a `search-receipt` CLI command
  beside the unchanged `search_records`/`search` surfaces. The receipt
  (`artifact-memory/search-receipt/v1`) reports the raw query, matched record
  IDs, the projection's `source_record_set_digest`, and the integrity-gate
  outcome.
- Issue the receipt inside the same gated read transaction that serves the
  query, so the digest and the matches come from one verified snapshot; a
  tampered index produces a typed `projection-unavailable` failure instead of
  a vouched receipt.
- Share one query-failure classifier with `search_records` so both surfaces
  classify identically; its implementation remains message-based until the
  error-code classification lands (issue #107).
- Keep `search_records`, `related`, `provenance`, projection receipts, and
  all pinned fixtures byte-identical.

## Compatibility

- Additive only: new function, new subcommand, new receipt schema; no
  existing schema, CLI output, fixture, or receipt shape changes.
- The pinned scan-projection fixture, vertical slice, and WITS conformance
  tests are unaffected by construction and must stay green.

## Authority and limitations

A search receipt is informational evidence pinning results to the exact
canonical record set that produced the index. It does not certify record
truth, semantic relevance, freshness of the source records, or grant any
execution, mutation, disclosure, or approval authority. Ordering remains
`record_id`-only until conditional bm25 lands (issue #109).

## Evidence

- GitHub issue: <https://github.com/joefeser/artifact-memory/issues/106>
- Contract: `docs/contracts/v0-filesystem-and-projections.md`
- Receipt schema: `artifact_memory/schemas/core/search-receipt.v1.schema.json`
- Slice: `artifact_memory/search_receipt_slice.py`, replayed by
  `python3 scripts/run_search_receipt_slice.py --check` against
  `fixtures/synthetic/search-receipt/v1/expected-receipt.json`
- Unit fixtures: `tests/test_projection.py`
  (`test_search_receipt_pins_results_to_source_record_set`,
  `test_search_receipt_refuses_tampered_index`) and
  `tests/test_cli.py` (`test_search_receipt_pins_digest_through_cli`)
