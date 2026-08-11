# WITS boundary conformance fixture

This synthetic fixture extends the pinned `SyntheticOrders` TraceMap vertical
slice with one opaque WITS `owner-meaning` projection reference. This frozen
legacy identifier means an opaque projection of human-originated meaning
admitted by WITS; it does not assign origination or ownership of meaning to
WITS. Artifact Memory
binds exact source revisions, sensitivity/freshness selection, TraceMap evidence,
the WITS contract commit, and BSL provenance without copying WITS implementation
code or product-owned schema text.

The proof exports a bounded informational context pack, recalls it with the
independent reader, deletes and rebuilds SQLite from canonical records, creates
an encrypted backup, and performs an isolated restore. It ends explicitly before
HACP Task Packet or Route Task creation and performs no execution or mutation.

`projection-response-v2.json` is the independently supplied, opaque synthetic
provider response template. The synthetic provider adds the digest of the
actual request at runtime, binding the response to the exact claim revision,
TraceMap binding, projection kind, and WITS contract anchor without embedding
platform-dependent generated-index bytes. It proves the
Artifact Memory process boundary only; it is not evidence of live WITS
interoperability or authority-safe coordinated use.

`expected-receipt.json` and `receipt.md` are machine-checked and human-readable evidence.
Replay both with `python3 scripts/run_wits_conformance.py --check`; the standard
conformance command invokes the same check.

The historical receipt limitation uses the older phrase “WITS owner meaning.”
Decision 0020 supersedes that wording without changing the released fixture or
its digest. Neither wording grants task, decision, disclosure, routing, or
execution authority.
