# Independent exchange conformance receipt

- Outcome: `complete`
- Receipt: `independent-exchange-conformance-receipt://6027bae5b43420a6083cb885d94a8bb767efb4e16cdea836df5048bb8540bd79`
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
