# Adapter manifest conformance receipt

- Reference adapter: `adapter://synthetic/reference-reader`
- Provider-read adapter: `adapter://artifact-memory/tracemap-evidence` (local read only)
- Success outcome: `succeeded` (`adapter-receipt://a6e284e09d0d76d6e51199065c959d18371d26bd84d7dd2a6ba46df1d7ad4dd7`)
- Failure outcome: `failed` / `authority-boundary` (`adapter-receipt://f29faf89c0fd692225136c902e96096f51dbc4b6953bccf33c936a71ba4360dc`)
- Extension cases: optional-preserved=succeeded, malformed-rejected=failed, unsupported-required-rejected=failed, invalid-identifier-rejected=failed
- Conformance receipt: `adapter-manifest-conformance-receipt://3bb0bdd2993650df4df5b3f14eafb5930ec936f5eeb24ba71db6a146fa9de7c6`

Authority boundary: record contents do not authorize adapter execution.
