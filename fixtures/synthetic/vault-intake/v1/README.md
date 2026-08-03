# Synthetic vault intake fixture

This fixture proves hash, immutable registration, post-write verification,
canonical artifact/version record creation, duplicate replay, and explicit
digest-mismatch quarantine in a temporary vault. The regression suite also
injects a publication failure and proves no partial or final object is left
behind.

No file is derived from a private vault, task transcript, customer, browser
session, credential, or production artifact. Receipts contain no local paths.
