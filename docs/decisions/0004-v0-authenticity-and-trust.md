# ADR 0004: v0 authenticity and trust distinctions

Status: accepted for v0
Date: 2026-07-30

Artifact identity answers what reference is being discussed. Integrity answers
whether the observed bytes or receipt match a digest. Provenance records where
an observation came from. Authenticity answers whether an issuer or signer is
verified for the intended audience. Authorization answers what an actor may
do. Trust is a separate receiving-policy judgment. None of these states
implicitly establishes another.

V0 accepts unsigned evidence only when its integrity is verified and labels it
exactly `integrity-verified / issuer-unverified`. A Git commit, content digest,
TraceMap extractor, rule catalog, or ACK receipt is not an operator signature
and cannot establish authenticity or trust. Cryptographic signature
verification, key rotation, revocation, expiry, delegation, and offline key
distribution are deferred; a signed input is unsupported, and an
authenticity-required input fails closed. No private keys or bearer material
belong in records or fixtures.
