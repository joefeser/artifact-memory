# Exchange admission conformance receipt

- Outcome: `complete`
- Receipt: `exchange-conformance-receipt://157630d75584f43279e9d9447abd406588727f4ef9bd2a8ef583c8b60018a8d8`
- Replay idempotent: `true`
- Contradictory input quarantined: `true`
- Bearer material rejected without echo: `true`
- Artifact retrieval: `not-attempted/separately-authorized`

| Case | Observed outcome | Result |
| --- | --- | --- |
| `admitted` | `admitted` | pass |
| `duplicate` | `duplicate` | pass |
| `partially-resolved` | `partially-resolved` | pass |
| `quarantined` | `quarantined` | pass |
| `rejected` | `rejected` | pass |
| `unsupported` | `unsupported` | pass |

Authority boundary: knowledge exchange grants no execution, disclosure, routing, spending, credential, deployment, merge, or mutation authority.
