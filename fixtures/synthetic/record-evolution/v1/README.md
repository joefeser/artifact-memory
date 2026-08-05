# Synthetic record-evolution proof

This fixture uses newly authored synthetic records. It proves one accepted
correction that supersedes an exact source revision and one rejected candidate.
The accepted record remains a new immutable revision and the rejected candidate
has no resulting record. No fixture content grants authority.

`source-record.json`, `candidate.json`, `accepted-record.json`, and
`expected-receipt.json` are canonical replay inputs and expected output. The
test suite reruns admission and compares the full schema-valid receipt.
