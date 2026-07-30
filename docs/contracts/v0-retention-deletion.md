# v0 retention, deletion, redaction, and tombstones

Removal receipts are scoped evidence, not global erasure claims. The v0
reference layer can create a requested or not-authorized receipt and a
non-sensitive tombstone, but it does not delete bytes, purge backups, rewrite
Git history, or mutate a vault without a separately authorized operation.

Managed backup retention keeps an overall deletion state partial or pending
until the named backup generation expires or a separately evidenced purge
completes. Unknown or unmanaged replicas remain a visible limitation.
Generated indexes are disposable and rebuild without deleted canonical
content. Redacted derivatives and superseded records retain only the minimum
non-sensitive receipt needed to explain the lifecycle.
