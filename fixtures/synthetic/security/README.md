# Synthetic security-boundary fixtures

These fixtures are newly authored synthetic cases. They are not redacted
production data and do not contain credentials, private records, or artifact
bytes.

The negative fixture describes values that a future validator must reject
without embedding a real secret-like value. For
`case: "forbidden-sensitive-field"`, the required outcome is exactly
`outcome: "reject"` with `authority_granted: false`; quarantine is not an
equivalent result.

This is a design fixture for the future validator, not generated conformance
evidence. Issue #14 owns the executable CLI and machine-readable receipt
contract, and issue #22 owns admission outcomes and receipts. Those stories
must add the versioned schema, deterministic validator, and generated
human-readable receipt before claiming the input-to-outcome seam is complete.

`authenticity-v0-v2.json` is executable conformance evidence for issue #35. It
covers accepted unsigned integrity evidence, required-authenticity rejection,
unsupported signed input, failed integrity, and authenticated transport that
does not authenticate the subject issuer. Record-signature verification is
deferred in v0, so unknown-key, expired-key, delegated-key, and signature-valid
vectors are deliberately absent rather than simulated. No signing keys,
credentials, or bearer material appear in the fixture.

The earlier `authenticity-unsigned.json` and
`authenticity-required-rejected.json` files are retained as v1 design examples;
they are not executable v2 vectors and do not define the reference API.
