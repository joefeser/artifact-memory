# Portable manifest conformance receipt

- Outcome: `complete`
- Positive equivalent-tree cases: 2
- Layouts per positive case: 3 (linux, macos, windows)
- Negative outcomes: collision=1, unsupported=1, partial=1
- Container/tree identities distinct: `true`
- Vector-set digest: `sha-256:7792b98e6c51b4efdae40b6ff6c472181ba719741e59ce8528ac3517343a00d6`
- Receipt: `manifest-conformance-receipt://92b6ce5e5b4a0ede09b21ff20813204d8ba3b85320bfd8557811ece45a0e826c`

All vectors are newly authored synthetic data. Mount roots are test inputs, never durable identity. CI replays this same receipt on macOS, Ubuntu, and Windows; deferred host semantics remain tracked by #24 and archive semantics by #25.
