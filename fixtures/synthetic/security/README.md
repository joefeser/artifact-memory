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
