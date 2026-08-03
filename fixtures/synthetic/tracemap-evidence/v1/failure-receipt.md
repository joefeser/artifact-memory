# TraceMap adapter failure-surface receipt

- Provider contract anchor: `9a252f12f781ae2a0aab52b5faa53601440a2a3b`
- Aggregate outcome: `complete`
- Conformance receipt: `tracemap-failure-conformance-receipt://8bf77e4ff9ef7a03e54374de75c8bbb17395011938cfbb982a47e63d876f82fe`
- Protected input echoed: `false`
- Local path echoed: `false`

| Case | Observed outcome | Result |
| --- | --- | --- |
| `adapter-failed` | `adapter-failed` | pass |
| `commit-binding-mismatch` | `commit-binding-mismatch` | pass |
| `complete` | `complete` | pass |
| `configuration-identity-unavailable` | `configuration-identity-unavailable` | pass |
| `digest-mismatch` | `digest-mismatch` | pass |
| `partial-evidence-admitted` | `partial-evidence-admitted` | pass |
| `provider-record-not-found` | `provider-record-not-found` | pass |
| `repository-binding-mismatch` | `repository-binding-mismatch` | pass |
| `required-artifact-missing` | `required-artifact-missing` | pass |
| `rule-catalog-unavailable` | `rule-catalog-unavailable` | pass |
| `schema-unsupported` | `schema-unsupported` | pass |
| `source-version-unavailable` | `source-version-unavailable` | pass |
| `trace-output-invalid` | `trace-output-invalid` | pass |
| `unsafe-provenance-rejected` | `unsafe-provenance-rejected` | pass |

Authority boundary: informational evidence only; no execution, routing, disclosure, approval, or mutation authority.
