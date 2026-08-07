# Decision 0009: bind scan scope to policy identity and separate attempt completeness

Status: accepted
Date: 2026-08-01

Issue: #7.

Artifact Memory identifies a scan policy by the canonical SHA-256 digest of
its logical endpoint, relative root, comparison behavior, link behavior,
exclusions, and extensions. Runtime resource limits and cancellation are
attempt facts recorded in the receipt rather than policy identity. This lets
partial and complete manifests from the same semantic scope remain comparable
without hiding the bounds that affected either attempt.

Declared exclusions are applied before entry metadata or content reads and are
reported separately. They define out-of-scope paths and do not alone weaken a
complete claim. Unexpected unreadable, unstable, unsupported, collision, and
resource-limit observations remain explicit and prevent complete success.

The v2 receipt binds both manifest identity and normalized tree digest, along
with logical scope, policy digest, implementation identity, timestamps, and
separate warnings and failures. Absolute resolver paths remain local and never
enter the portable receipt.

Consequences: v1 policy and receipt schemas remain packaged for compatibility,
while the reference scanner emits and verifies v2. A UUID v4 attempt ID makes
separate attempts intentionally distinct even when their timestamps and other
facts match. Filesystem completeness remains
separate from provider analysis completeness and grants no authority.
