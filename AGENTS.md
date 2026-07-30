# Repository Operating Rules

Artifact Memory is intended to become a public open-source repository. Treat
every commit, branch, issue, pull request, workflow log, and fixture as public
from the moment it is created, even while repository visibility is private.

## Non-negotiable boundaries

1. Never commit real vault records, artifact bytes, customer material, private
   strategy, raw task transcripts, credentials, browser state, or machine-local
   resolver configuration.
2. Use synthetic fixtures only. Synthetic data must not be lightly redacted
   production or customer data.
3. Canonical knowledge and protocol records are versioned text. SQLite,
   NDJSON, HTML, graphs, and search indexes are generated and replaceable.
4. Keep artifact identity, content identity, location observations, and
   semantic meaning distinct.
5. Do not treat a mount point, absolute path, filename, drive letter, hostname,
   provider URL, or bearer URL as durable identity.
6. Knowledge exchange never implies execution, mutation, spending,
   deployment, credential, declassification, or approval authority.
7. Unknown required extensions fail closed. Unknown optional extensions must
   be preserved without being interpreted.
8. Contracts and schemas precede broad implementation. Add conformance
   fixtures for normative behavior.
9. Claims require provenance. Incomplete scans, unreadable entries,
   unsupported schemas, and unverified artifacts must remain explicit.
10. Never present a generated index as the only copy of durable knowledge.

## Working style

- Prefer small contract-first changes.
- Record consequential decisions under `docs/decisions`.
- Use GitHub issues for bounded implementation work.
- Use GitHub Discussions for open design questions.
- Keep public protocol behavior separate from private vault policy.
- Add or update synthetic fixtures with schema behavior.
- Include security and compatibility implications in pull requests.

## Completion standard

A feature is not complete because its schema parses. Prove the relevant seam
through a synthetic end-to-end fixture and a human-readable receipt. For
cross-platform claims, provide evidence from the platforms or mount layouts
named by the claim.

