# Canonical record and content conformance receipt

- Outcome: `complete`
- Canonical vectors: 4
- Invalid vectors rejected: 5
- Revision examples: 4
- Zero-byte content: `verified`
- Large content: `verified` (5242880 bytes)
- Verification outcomes: verified=2, mismatch=1, unreadable=1, unsupported=1
- Vector-set digest: `sha-256:38eb24fc2fd72f7043ca904d347c8bf6cdb77d6c9e23896300f26286d71ab1f5`

The fixture is newly authored synthetic data. It proves deterministic v0 canonical bytes, revision digests, and exact-content verification without using Git, paths, timestamps, or storage locations as identity.
