# Coordination outbox conformance fixture

This synthetic AM-4 proof treats the local canonical coordination pair set as
the outbox. It appends 100 generated TaskPacket records while the synthetic hub
is unavailable, verifies that failed delivery changes no local pair, restores
the hub, and proves exact-count convergence plus a byte-identical retry.

No fixture contains private vault material, deployment topology, or authority.
