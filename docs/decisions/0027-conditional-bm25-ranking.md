# 0027: Conditional bm25 ranking

## Status

Accepted, 2026-08-28, for issue
<https://github.com/joefeser/artifact-memory/issues/109>.

## Context

The corrected retrieval audit of `153f2843` (finding F3) showed search
ordering was record_id only — a zero relevance signal degrading findability
at vault scale. The independent second opinion permitted bm25 ranking only
conditionally: order is corpus-dependent (an order flip was demonstrated
from unrelated added records), so it must never be presented as
authoritative, and the receipt must label the order and disclose corpus
dependence.

## Decision

- Both `search` and `search-receipt` accept `--rank`, ordering results by
  FTS5 bm25 with a deterministic record_id tiebreak for equal scores.
  Default order remains record_id alone; the flag is the caller's opt-in.
- Ranking uses the explicit `bm25(records_fts)` function, not the mutable
  `rank` alias: a persisted FTS5 rank configuration
  (`INSERT INTO records_fts(records_fts, rank) …`) can steer `ORDER BY rank`
  on an index that still passes contract validation and `integrity_check`,
  while the explicit function ignores it. Supersession exclusion composes in
  the same SQL statement, so no path issues per-result lifecycle queries.
- Ranked receipts carry an optional `result_order` object —
  `ranking: bm25`, `tiebreak: record-id`, `authoritative: false`,
  `corpus_dependent: true` — so the order claim is machine-checkable and
  self-disclaiming. Default receipts omit the field entirely, keeping the
  pre-ranking v1 shape.
- Ranking composes with both query grammars and with supersession exclusion,
  preserving relevance order among survivors inside the same gated read.
- The checked-in slice demonstrates, deterministically, that bm25 inverts
  record_id order on a paired corpus and that adding three lexically
  unrelated records (sharing no query term) flips the ranked order, so the
  corpus-dependence disclosure is proven, not asserted.

## Compatibility

- Additive: defaulted keyword argument, CLI flag, optional receipt field; no
  schema, output, or fixture shape changes; default behavior unchanged.
- Measured (issue #117, 2026-08-28; generator profile
  `rank-measure/v1:corpus-v2:summaries-v1`, corpus digests recorded in the
  performance baseline): ranked search is at cost parity with unranked
  search (56.2 ms vs 56.0 ms at 1,000 records; 287.9 ms vs 288.4 ms at
  5,000 — per-query cost is dominated by revalidation), and forty distinct
  single-record additions — query-term-sharing and unrelated alike — caused
  no ranked-order flip at those scales. The deterministic flip proven by
  the slice is a small-corpus phenomenon; corpus dependence remains a
  disclosed property of ranked order.

## Authority and limitations

Ranked order is a findability aid over restricted lexical meaning. It grants
no authority, does not certify relevance or record truth, and any result's
rank can shift when unrelated records are added to or removed from the vault.

## Evidence

- GitHub issue: <https://github.com/joefeser/artifact-memory/issues/109>
- Contract: `docs/contracts/v0-filesystem-and-projections.md`
- Receipt schema: `artifact_memory/schemas/core/search-receipt.v1.schema.json`
  (`result_order`)
- Slice: `artifact_memory/search_ranking_slice.py`, replayed by
  `python3 scripts/run_search_ranking_slice.py --check` against
  `fixtures/synthetic/search-ranking/v1/expected-receipt.json`
- Unit fixtures: `tests/test_projection.py`
  (`test_ranked_search_orders_by_bm25_with_record_id_tiebreak`,
  `test_ranked_search_ties_break_by_record_id_and_compose_with_other_modes`)
  and `tests/test_cli.py` (`test_search_ranking_through_cli`)
- Measurements: `python3 scripts/measure_ranked_search.py` (issue #117),
  with observed values recorded in
  `docs/contracts/v0-performance-baseline.md`
