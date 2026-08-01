# Canonical record and content conformance receipt

- Outcome: `complete`
- Canonical vectors: 4
- Invalid vectors rejected: 5
- Revision examples: 4
- Zero-byte content: `verified`
- Large content: `verified` (5242880 bytes)
- Verification outcomes: verified=2, mismatch=1, unreadable=1, unsupported=1
- Vector-set digest: `sha-256:1d47caa7a2390e8b6e33ec5f0434e772456b2f149b038d6de50b72f64ab4c6f7`

The fixture is newly authored synthetic data. It proves deterministic v0 canonical bytes, revision digests, and exact-content verification without using Git, paths, timestamps, or storage locations as identity.
