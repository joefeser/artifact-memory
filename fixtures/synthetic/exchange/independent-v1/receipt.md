# Independent exchange conformance receipt

- Outcome: `complete`
- Receipt: `independent-exchange-conformance-receipt://52c9470e8620a80902d29b1966108758da3f29f62278086900b24f059d549071`
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
| `legacy_malformed_required_declaration` | `quarantined` | `true` |

Authority boundary: knowledge exchange grants no execution, disclosure, routing, spending, credential, deployment, merge, or mutation authority.
