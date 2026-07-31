# Synthetic v0 authenticity conformance receipt

- Outcome: `complete`
- Receipt: `authenticity-conformance-receipt://synthetic/514d5a2b74cc0d78e9ada19ca5ff7dc06e020728e5898e4374a1886fc45fa3d2`
- Vector set: `sha-256:1ba7fab9971ba669d0d01b70b1142e37d13a9fa68f97b3bc5c4acd886a63e3e6`
- Assessment schema: `artifact-memory/authenticity-receipt/v2`
- Authority: `assessment grants no execution, disclosure, authorization, or trust`

| Case | Outcome | Integrity | Authenticity | Transport |
| --- | --- | --- | --- | --- |
| `unsigned-integrity-verified` | `accepted` | `integrity-verified / issuer-unverified` | `issuer-unverified` | `not-evaluated` |
| `required-authenticity-fails-closed` | `rejected` | `integrity-verified / issuer-unverified` | `authenticity-required-unmet` | `not-evaluated` |
| `signed-input-is-unsupported` | `unsupported` | `integrity-verified / issuer-unverified` | `signed-input-unsupported` | `not-evaluated` |
| `tampered-integrity-fails` | `rejected` | `integrity-failed` | `issuer-unverified` | `not-evaluated` |
| `authenticated-transport-does-not-authenticate-issuer` | `accepted` | `integrity-verified / issuer-unverified` | `issuer-unverified` | `channel-authenticated / subject-issuer-unverified` |

This receipt uses only newly authored synthetic data and contains no signing keys or credentials.
