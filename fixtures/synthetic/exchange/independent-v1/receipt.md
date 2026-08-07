# Independent exchange conformance receipt

- Outcome: `complete`
- Receipt: `independent-exchange-conformance-receipt://33c5b363dae2394bf94d8807ba1b2377434a16e3fb29485781b8f934ac5bc2fb`
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
| `legacy_required_declaration` | `quarantined` | `true` |
| `legacy_malformed_required_declaration` | `admitted` | `true` |
| `mixed_required_and_legacy_extensions` | `admitted` | `true` |

Authority boundary: knowledge exchange grants no execution, disclosure, routing, spending, credential, deployment, merge, or mutation authority.
