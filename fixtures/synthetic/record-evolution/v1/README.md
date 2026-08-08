# Synthetic record-evolution proof

This fixture uses newly authored synthetic records. It proves one accepted
correction that binds a `supersedes` relationship to an exact source revision.
The accepted record remains a new immutable revision. No rejected-path or
predecessor-transition fixture exists in this v1 directory, and no fixture
content grants authority.

`source-record.json`, `candidate.json`, `accepted-record.json`, and
`expected-receipt.json` are canonical replay inputs and expected output. The
test suite reruns admission and compares the full schema-valid receipt.
