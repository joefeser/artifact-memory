# Decision 0008: pair logical identities with canonical revision and content digests

Status: accepted
Date: 2026-08-01

Issues: #4 and #5. Discussion #29 records the original identity question.

Artifact Memory keeps a stable namespaced `record_id` separate from the digest
of each exact canonical revision. Exact content uses a location-neutral
SHA-256-derived `content_id`; optional secondary digests add integrity evidence
without changing identity.

V0 canonical digest inputs exclude fractional numbers and integers outside the
widely interoperable integer range. This is narrower than arbitrary JSON but
provides reproducible bytes without depending on a language's floating-point
formatter. A future numeric expansion must be versioned and backed by
cross-language vectors.

Draft mutation is allowed before durable exchange. Accepted and sealed
revisions are immutable, and supersession preserves the prior revision. Git and
generated database identities are never protocol identities.

Consequences: existing `content-object/v1` remains readable, while v2 makes
digest-derived identity and secondary-digest verification explicit. Readers
fail closed on malformed identity claims and return typed unsupported outcomes
for unknown algorithms.
