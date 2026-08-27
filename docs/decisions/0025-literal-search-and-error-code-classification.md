# 0025: Literal search mode and error-code classification

## Status

Accepted, 2026-08-27, for issue
<https://github.com/joefeser/artifact-memory/issues/107>.

## Context

The corrected retrieval audit of `153f2843` (findings F2 and F4, confirmed
and understated in v1) showed that the only search mode exposed raw FTS5
MATCH syntax, so a leading or embedded hyphen could be silently reinterpreted
as column-filter syntax, and query-invalid classification string-matched
SQLite error text ("fts5: syntax error" and friends), which is brittle across
SQLite upgrades. On the reference runtime (SQLite 3.52.0) a raw hyphenated
query such as `alpha-beta` fails as `no such column: beta` — the
reinterpretation is observable, not hypothetical. The audit verified that all
caller-side errors on this path surface SQLite result code 1 (SQLITE_ERROR).

## Decision

- Both `search` and `search-receipt` accept `--literal`. Literal mode treats
  the query as one literal term with significant bytes: the term is quoted
  as a single FTS5 string (embedded double quotes doubled, FTS5's only
  string escape) so its tokens must appear as an adjacent phrase, and the
  matched record's indexed summary or labels must also contain the query's
  case-folded bytes. Punctuation and spelling are therefore significant —
  literal `alpha-beta` does not match adjacent `alpha beta` text — while
  matching stays case-insensitive and single-term. An empty literal query
  returns `query-invalid` before the index is opened, so a missing or
  invalid index cannot outrank the caller-input failure.
- Raw mode remains the default and passes the query to FTS5 unmodified.
- Query failures classify on `sqlite_errorcode & 0xff`, not message text:
  code 1 is `query-invalid`; every other code is `projection-unavailable`.
- The projection contract requires `records_fts` to be an FTS5 virtual
  table. A regular table with the expected columns passes column and
  integrity checks but cannot serve MATCH, and its code-1 failure would
  otherwise misclassify a valid query as `query-invalid`; the contract
  rejects it as `projection-unavailable` first.
- Search receipts record `query_mode` (`raw` or `literal`) beside the query
  digest, added to the v1 receipt schema as an optional field so existing
  receipts remain valid while every newly issued receipt identifies which
  grammar produced its results. The digest still pins the query exactly as
  the caller typed it in either mode.
- Document the query-surface boundary in the projection contract: search is
  lexically restricted to `meaning.summary` and labels, is an ungated
  term/adjacency/prefix confirmation oracle over that restricted meaning, and
  applies no context-pack exclusion policy — context export remains the
  surface that counts and reports exclusions.

## Compatibility

- Additive: a defaulted keyword argument on both library functions, a CLI
  flag, no schema, receipt, or output-shape changes. Raw behavior is
  unchanged except that classification now keys on the error code; the
  previously matched messages all carried code 1 on the reference runtime, so
  observable outcomes are identical there.
- `sqlite_errorcode` requires Python 3.11+, already the package floor; on it,
  FTS5 syntax errors were verified to carry code 1 on SQLite 3.52.0.

## Authority and limitations

Literal mode removes query-syntax reinterpretation for one term; it is not a
multi-term phrase interface, grants no authority, and changes nothing about
what search can see: restricted lexical meaning only, no context exclusions,
`record_id` ordering until conditional bm25 lands (issue #109).

## Evidence

- GitHub issue: <https://github.com/joefeser/artifact-memory/issues/107>
- Contract: `docs/contracts/v0-filesystem-and-projections.md`
- Slice: `artifact_memory/search_literal_slice.py`, replayed by
  `python3 scripts/run_search_literal_slice.py --check` against
  `fixtures/synthetic/search-literal/v1/expected-receipt.json`
- Unit fixtures: `tests/test_projection.py`
  (`test_literal_search_matches_one_term_without_syntax_reinterpretation`,
  `test_search_failure_classification_uses_sqlite_error_code`,
  `test_search_receipt_literal_mode_pins_typed_query`) and
  `tests/test_cli.py` (`test_search_literal_mode_through_cli`)
