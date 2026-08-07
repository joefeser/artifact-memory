# Independent exchange conformance receipt

- Outcome: `complete`
- Receipt: `independent-exchange-conformance-receipt://4621300489e615209adb4aa98a2bced96ee01edd9b8f2d70b79e875938dc6b84`
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

Authority boundary: knowledge exchange grants no execution, disclosure, routing, spending, credential, deployment, merge, or mutation authority.
