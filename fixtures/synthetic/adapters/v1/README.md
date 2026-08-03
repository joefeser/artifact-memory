# Synthetic adapter-manifest conformance fixture

This newly authored fixture validates one independent reference-reader
manifest and emits a deterministic success receipt. A second vector differs
only by claiming that record contents authorize execution; it must fail closed
with an `authority-boundary` diagnostic and JSON path.

The separate adapter-manifest conformance runner validates
`tracemap-read-manifest.json` and its exact local-read-only capability profile.
The synthetic TraceMap vertical-slice path validates the provider binding
schema; it does not load or validate this manifest or invoke adapter code.

The checked JSON and Markdown receipts contain no executable code, credentials,
private records, real filesystem paths, provider content, or machine-local
resolver configuration.
