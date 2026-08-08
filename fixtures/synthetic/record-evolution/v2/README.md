# Synthetic record-evolution v2 proof

These newly authored synthetic fixtures prove the bounded #83 repair. Full
replay checks candidate identity, accepted supersession with an immutable
predecessor transition, a typed rejected outcome with no record, an accepted
`disputes` relationship bound to an exact source revision, and candidate-level
uncertainty without derivative metadata.

The composed context fixture passes the superseded predecessor and accepted
replacement directly to `export_context`. Negotiated context-pack v4 excludes
the predecessor by lifecycle before freshness and reports only an aggregate
lifecycle count. Its caller-selected IDs are explicitly unauthenticated and
grant no authority.

Every admission path has a machine-readable receipt and a checked human-readable
projection. `current-context-pack.json` and `current-context-receipt.md` are the
corresponding machine and human context evidence. No fixture contains real vault,
customer, credential, transcript, or machine-local material.
