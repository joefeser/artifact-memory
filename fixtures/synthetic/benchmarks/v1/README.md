# Benchmark profile v1 fixture

This directory is versioned for
`artifact-memory/benchmark-profile/v1`, not for a receipt schema. The checked
`expected-receipt.json` declares
`artifact-memory/benchmark-receipt/v2`; consumers must dispatch from that
`schema_id`.

The profile also declares
`artifact-memory/synthetic-benchmark-record-generator/v1`. Records generated
for projection timing are ephemeral synthetic inputs, not durable canonical
knowledge. The expected receipt binds the generator identifier and exact
generated record-set digest. A semantic generator change requires a new
generator identifier and regenerated checked evidence.
