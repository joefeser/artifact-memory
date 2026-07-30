# v0 performance and resource baseline

The benchmark harness creates a synthetic tree with repeated and unique
content, a deep path, and a generated canonical-record set. It measures scan
and rebuildable projection wall time on the runner that executes it. The
measurements are descriptive and machine-specific; they are not a universal
throughput or memory promise.

The scan API accepts caller-owned entry and byte limits plus a cancellation
check. A resource limit produces a `partial` receipt with a
`resource-limit` diagnostic. Cancellation produces a `cancelled` receipt with
a `cancelled` diagnostic. Archive decompression limits remain separately
typed. No large-file exemption silently bypasses a declared bound.
