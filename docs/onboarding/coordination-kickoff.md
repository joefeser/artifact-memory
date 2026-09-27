# Generate bounded coordination kickoff context

AM-5 turns an onboarded project's latest authenticated coordination snapshot
into a small informational startup pack. Complete
[coordination project onboarding](coordination-project-onboarding.md) and sync
before using it.

```sh
artifact-memory kickoff \
  --project 11111111-1111-4111-8111-111111111111 \
  --vault /path/to/private-coordination-vault \
  --out /path/to/generated-kickoff
```

An unambiguous project display name may replace the UUID. If two project links
share a display name, the command fails with `kickoff-project-ambiguous`; use
the UUID. The output directory receives `kickoff-pack.json` and `kickoff.md`.
Without `--out`, the human-readable prompt is printed. Add `--json` to print
the canonical pack instead.

The generator verifies the current successful-sync marker, receipt identity,
authorized membership count and digest, every authorized record's exact pair,
the AM-9 project binding, and complete TaskPacket predecessor chains. It then
selects the unique current open leaf with the lexicographically greatest
ULID-bearing `taskId`. Its observation time and hub scope generation qualify
the result; it is not a freshness or global-state claim beyond that receipt.

Any local coordination revision for the project that is absent from current
authorized membership causes `kickoff-record-not-admitted`. This includes
pending, rejected, quarantined, or suppressed revisions: mere local presence
cannot make one current. Missing or tampered receipt evidence, a local-set
mismatch, or a broken/forked predecessor graph also fails typed.

`acceptanceCommand`, title, expected result, definition of done, and scope
fence remain untrusted record data. The Markdown uses JSON encoding plus HTML
escaping, labels the command `DO NOT EXECUTE`, and never invokes it. A kickoff
pack grants no execution, mutation, routing, disclosure, credential, spending,
deployment, approval, or merge authority. Resolve all such authority through
an independent authenticated contract.

Run the public synthetic proof with:

```sh
python3 scripts/run_coordination_kickoff_conformance.py --check
```

The fixture includes newlines, shell substitutions, metacharacters, HTML, and
instruction-like prose. It proves that these bytes remain inert rendered data
and that no synthetic marker is created.
