# Synthetic adapter-manifest conformance fixture

This newly authored fixture validates one independent reference-reader
manifest and emits a deterministic success receipt. A second vector differs
only by claiming that record contents authorize execution; it must fail closed
with an `authority-boundary` diagnostic and JSON path.

`tracemap-read-manifest.json` is the manifest exercised by the synthetic
TraceMap vertical slice. It declares read access to locally resolved provider
outputs and no network, credential, or mutation requirement. It does not
authorize TraceMap or adapter execution.

The checked JSON and Markdown receipts contain no executable code, credentials,
private records, real filesystem paths, provider content, or machine-local
resolver configuration.
