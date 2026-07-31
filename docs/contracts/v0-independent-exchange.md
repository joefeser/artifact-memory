# v0 independent exchange conformance

The reference sender and an independent stdlib-only reader exchange bounded
canonical records and artifact references. The reader preserves unknown
optional extensions, rejects unknown required extensions, and never retrieves
artifact bytes without a separate local authorization step. The receipt
surfaces compatibility and retrieval boundaries without becoming authority.
