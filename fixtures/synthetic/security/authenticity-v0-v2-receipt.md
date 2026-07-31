# Synthetic v0 authenticity conformance receipt

- Outcome: `complete`
- Receipt: `authenticity-conformance-receipt://synthetic/02e88faacdc0cd4f1acf65765b83cf63e7476269538a8315a22d0ca1e313b79d`
- Vector set: `sha-256:e6561a9769cd70a174b0af960e6e0e67ef25789a6fc6ce5648dcb7d58dfd90a9`
- Assessment schema: `artifact-memory/authenticity-receipt/v2`
- Authority: `assessment grants no execution, disclosure, authorization, or trust`

| Case | Outcome | Integrity | Authenticity | Transport |
| --- | --- | --- | --- | --- |
| `unsigned-integrity-verified` | `accepted` | `integrity-verified / issuer-unverified` | `issuer-unverified` | `not-evaluated` |
| `required-authenticity-fails-closed` | `rejected` | `integrity-verified / issuer-unverified` | `authenticity-required-unmet` | `not-evaluated` |
| `signed-input-is-unsupported` | `unsupported` | `integrity-verified / issuer-unverified` | `signed-input-unsupported` | `not-evaluated` |
| `tampered-integrity-fails` | `rejected` | `integrity-failed` | `issuer-unverified` | `not-evaluated` |
| `unverified-integrity-fails-closed` | `rejected` | `integrity-unverified` | `issuer-unverified` | `not-evaluated` |
| `authenticated-transport-does-not-authenticate-issuer` | `accepted` | `integrity-verified / issuer-unverified` | `issuer-unverified` | `channel-authenticated / subject-issuer-unverified` |

This receipt uses only newly authored synthetic data and contains no signing keys or credentials.
