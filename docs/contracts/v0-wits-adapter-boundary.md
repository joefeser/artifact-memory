# v0 Artifact Memory ↔ WITS adapter boundary

The adapter accepts exact Artifact Memory record revisions, sensitivity and
disclosure constraints, freshness, and optional TraceMap evidence references.
It emits an opaque WITS projection reference and a deterministic admission
receipt. WITS owns owner meaning, decisions, readiness, task preparation,
routing, authority, and reconciliation; Artifact Memory does not recreate
those schemas or interpret their meaning.

Stale revisions, conflicts, unsupported projections, disclosure failures,
unavailable evidence, and authority-bearing requests remain explicit. The
fixture terminates before HACP task creation or execution, so this adapter does
not claim authority-safe coordination until a separately authenticated WITS
process proves the downstream boundary.
