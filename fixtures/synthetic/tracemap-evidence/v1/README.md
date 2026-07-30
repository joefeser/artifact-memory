# Synthetic TraceMap evidence packet

This packet mirrors the pinned TraceMap v1 artifact shapes without importing
TraceMap schemas into Artifact Memory core. `index.sqlite` is intentionally
generated from `index.sqlite.sql` during the conformance test; generated
indexes are replaceable and are never the durable copy of the evidence.

The provider contract anchor used by the adapter is TraceMap commit
`9a252f12f781ae2a0aab52b5faa53601440a2a3b`. The fixture's source commit is a
synthetic identity, not a real repository commit. The selected facts describe
one property declaration and one read access, and do not claim runtime use or
correctness. Unsigned provider evidence is labeled exactly
`integrity-verified / issuer-unverified`.
