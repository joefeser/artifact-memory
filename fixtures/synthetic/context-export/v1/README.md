# Synthetic bounded context-export fixture

This newly authored fixture proves #20 with one public current record, one
private record, one stale record, and two generic provider references. The
selection authorizes all record identities but exports only the public current
record; it authorizes only one provider record. Exclusion receipts contain
counts, not protected identities. The independent stdlib-only reader recalls
the selected summary and references without retrieving bytes or receiving
execution, mutation, disclosure, or routing authority.
