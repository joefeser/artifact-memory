# Synthetic revocation-propagation proof

This fixture is newly authored synthetic evidence. It proves a tombstone-bound
revocation envelope, one acknowledged recipient, one unavailable recipient,
aggregate partial completion, and suppression from generated projection and
context selection. It does not claim global deletion, cryptographic erasure,
or authority.

The directory persists the canonical source record, deletion receipt,
tombstone, envelope, recipient acknowledgements, and aggregate receipt. Tests
replay the workflow and compare the complete digest-bound artifacts.
