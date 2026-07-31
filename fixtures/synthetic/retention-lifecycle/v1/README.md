# Synthetic retention lifecycle fixture

This newly authored fixture proves the v0 lifecycle boundary without touching a
real vault, backup, or Git history. The initial projection contains one
synthetic accidental-ingestion record, one owner-approved deletion target, and
one retained record. The rebuilt projection contains the retained record and a
safe derivative bound to the accidental source by identifier only.

The checked receipt keeps the overall result partial because a named managed
backup generation is retained until expiry and unknown replicas cannot be
enumerated. Endpoint observations never claim global or cryptographic erasure.
All names, content, authority references, and endpoint observations are
synthetic; the portable endpoint identity illustrates the approved contract but
does not assert that the Proxmox guest exists or received a write.
