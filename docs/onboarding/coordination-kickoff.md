# Generate bounded coordination kickoff context

AM-5 turns an onboarded project's latest authenticated coordination snapshot
into a small informational startup pack. Complete
[coordination project onboarding](coordination-project-onboarding.md) and sync
before using it.

```sh
artifact-memory kickoff \
  --project 11111111-1111-4111-8111-111111111111 \
  --vault /path/to/private-coordination-vault
```

An unambiguous project display name may replace the UUID. If two project links
share a display name, the command fails with `kickoff-project-ambiguous`; use
the UUID. The command is read-only and prints the human-readable prompt to
stdout. Add `--json` to print the canonical pack instead; redirect stdout
explicitly when local persistence is intended.

The generator verifies the current successful-sync marker, receipt identity,
authorized membership count and digest, every authorized record's exact pair,
the AM-9 project binding, and complete TaskPacket predecessor chains. It then
selects the unique current open leaf with the lexicographically greatest
ULID-bearing `taskId`. Its observation time and hub scope generation qualify
the result; it is not a freshness or global-state claim beyond that receipt.

The CLI holds the authorized-projection lock through pack construction,
rendering, stdout emission, and flush. A concurrent pull cannot replace the
scope midway through that export. Library exporters can use `open_kickoff_pack`
to hold the same lock through their output operation; `build_kickoff_pack`
returns a detached receipt-bound snapshot.

## Evaluate repository-linked freshness

Freshness support is explicit and repo-bound. Add `--repo` to compare the
selected TaskPacket's optional coordination freshness extension with the
current commit of the exact onboarded repository:

```sh
artifact-memory kickoff \
  --project 11111111-1111-4111-8111-111111111111 \
  --vault /path/to/private-coordination-vault \
  --repo /path/to/onboarded-repository \
  --json
```

When the selected record declares
`https://artifact-memory.dev/extensions/coordination-freshness/v1`, the
generator emits `artifact-memory/coordination-kickoff-pack/v1`. It marks an
ancestor of the observed repository HEAD as `current` and a valid divergent
commit as `stale-verify`, binding both object IDs into the pack. An unavailable
object, changed HEAD, mismatched onboarding binding, or unsafe repository root
fails typed. Git replacement objects and ambient Git repository/configuration
overrides are disabled for the comparison.

Without `--repo`, the optional extension remains opaque and output stays on
the AM-5 v0 pack contract. Unknown optional extensions are never interpreted.
Unknown required extensions and a top-level `trueAsOfCommit` fail closed during
coordination-record validation. The generic knowledge context-pack v2-v4
contracts are unchanged.

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
python3 scripts/run_coordination_freshness_conformance.py --check
```

The fixture includes newlines, shell substitutions, metacharacters, HTML, and
instruction-like prose. It proves that these bytes remain inert rendered data
and that no synthetic marker is created.

The AM-6 fixture also creates deterministic divergent and ancestor-only Git
histories and proves the `stale-verify`/`current` distinction without using a
real repository or vault.
