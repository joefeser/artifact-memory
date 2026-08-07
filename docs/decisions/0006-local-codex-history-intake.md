# Decision 0006: local Codex-history intake boundary

Status: accepted for v0 implementation
Date: 2026-08-01
Linked issues: #37, #3, #20, #36

## Context

Codex task history can contain useful project decisions alongside raw
conversation, attachments, credentials, browser state, unrelated tasks, and
machine-local details. Making provider storage canonical or bulk-importing it
would collapse the public/private, source/meaning, retention, and authority
boundaries already accepted for v0.

## Decision

V0 uses a two-stage local adapter. The owner first selects exactly one task and
curates a bounded task-export object outside the repository. Artifact Memory
then transforms only allowlisted fields into separate draft decision, research,
workstream, and question records. The transformation has no session discovery,
network intake, attachment intake, or bulk mode.

The owner selection is represented by a private versioned policy. Real local
derivatives enter as private or restricted, require owner review, and retain
source-task and transformation provenance. The adapter makes no raw copy. The
source may remain source-system managed until an explicit expiry; any separate
Artifact Memory raw archive must be encrypted recovery evidence. Both remain
non-canonical, and expiry is not deletion authority.

Correction and deletion reuse #36. A correction creates a new identity and
supersedes rather than overwrites the earlier record. A deletion request is a
scoped informational receipt and performs no destructive action. Receiving a
derivative record grants no execution, routing, disclosure, declassification,
mutation, merge, deployment, spending, or credential authority.

The old v1 synthetic helper and declassification schema remain unchanged. The
strict intake uses a new policy, v2 declassification receipt, and v2 knowledge
records. This avoids silently reinterpreting existing v1 data or breaking the
pre-v2 helper call shape.

## Public evidence

Public conformance uses only newly authored synthetic data. A real private
dogfood run may publish one sanitized receipt containing counts and outcome but
no private source reference, content-derived digest, record identity, or
location. The private import artifacts and detailed receipt never enter Git.

## Consequences

The adapter cannot infer owner meaning directly from raw transcript rows;
curation is intentional. Obvious path and credential patterns fail closed, but
human review remains necessary. This trades automatic breadth for a narrow,
auditable seam that preserves the accepted privacy and authority boundaries.
