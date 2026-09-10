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
  the query as one literal query string, which may contain an adjacent
  multiword phrase. The query and validated indexed text are fully case-folded
  into a connection-local FTS5 table before the query is quoted as one FTS5
  string (embedded double quotes doubled, FTS5's only string escape), so its
  tokens must appear as an adjacent phrase. A matching summary or label must
  also contain the folded query bytes. Punctuation and spelling are therefore
  significant — literal `alpha-beta` does not match adjacent `alpha beta` text
  — while expanding Unicode folds such as `Straße`/`STRASSE` remain
  equivalent. An empty literal query
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
- Search receipts record the required `query_mode` (`raw` or `literal`) beside
  the query digest, so every valid v1 receipt identifies which grammar produced
  its results. The digest still pins the query exactly as the caller typed it
  in either mode. This requirement was corrected before v0.1.3 published the
  v1 receipt contract; earlier development-candidate receipts without the mode
  are not release contracts.
- Document the query-surface boundary in the projection contract: search is
  lexically restricted to `meaning.summary` and labels, is an ungated
  term/adjacency/prefix confirmation oracle over that restricted meaning, and
  applies no context-pack exclusion policy — context export remains the
  surface that counts and reports exclusions.

## Compatibility

- Additive relative to v0.1.2: a defaulted keyword argument on both library
  functions, a CLI flag, and the new search-receipt v1 contract. Raw behavior is
  unchanged except that classification now keys on the error code; the
  previously matched messages all carried code 1 on the reference runtime, so
  observable outcomes are identical there.
- `sqlite_errorcode` requires Python 3.11+, already the package floor; on it,
  FTS5 syntax errors were verified to carry code 1 on SQLite 3.52.0.

## Authority and limitations

Literal mode removes query-syntax reinterpretation for one literal query
string, including an adjacent multiword phrase. It grants no authority and
changes nothing about what search can see: restricted lexical meaning only and
no context exclusions. Default ordering remains `record_id`; optional bm25
ranking is separately available and non-authoritative.

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
