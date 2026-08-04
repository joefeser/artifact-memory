# Independent exchange conformance receipt

- Outcome: `complete`
- Receipt: `independent-exchange-conformance-receipt://cfba037e703f7738a33a4d4c0fa09a7adbc74a3bd38d20c4f369a9440ed0be0c`
- Sender: `artifact-memory-reference-sender-v2`
- Independent receiver: `stdlib-only-independent-reader-v2`
- Artifact retrieval: `not-attempted/separately-authorized`

| Case | Outcome | Compatible receipts |
| --- | --- | --- |
| `unknown_optional` | `admitted` | `true` |
| `unknown_required` | `quarantined` | `true` |
| `explicitly_supported_required` | `admitted` | `true` |
| `identical_manifest_declaration` | `admitted` | `true` |
| `legacy_opaque_record_extension` | `admitted` | `true` |

Authority boundary: knowledge exchange grants no execution, disclosure, routing, spending, credential, deployment, merge, or mutation authority.
