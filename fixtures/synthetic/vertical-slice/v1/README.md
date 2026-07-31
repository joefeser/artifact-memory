# TraceMap vertical slice v1

This fixture proves the issue #39 seam with wholly synthetic source. The
checked-in `source/` directory is copied into a deterministic Git repository,
then TraceMap is exported and executed at provider contract anchor
`9a252f12f781ae2a0aab52b5faa53601440a2a3b`.

Run the full provider-backed proof with:

```sh
python3 scripts/run_tracemap_vertical_slice.py \
  --tracemap-repo /path/to/tracemap \
  --output /new/empty/output/path
```

The runner selects the exact `Order.Status` declaration and Tier-1 semantic
access facts, then exercises validate, register, bind, index, context export,
encrypted backup, isolated restore, index rebuild, and context revalidation.
It generates a synthetic passphrase in memory and does not write it to the
receipt. The context pack excludes source text, analyzer logs, local paths, and
authority-bearing instructions.

`expected-receipt.json` is the public-safe human-readable receipt captured from
one successful exact-anchor run. TraceMap scan timestamps and encrypted-backup
salts may change packet and receipt identities on later runs; the source commit,
provider anchor, required stages, boundary labels, and successful outcomes are
the stable conformance assertions.

The binding and context contracts retain v1 read compatibility. Provider tool
identity, selected-record detail, rule, tier, and structured
`coverage_details` are additive; legacy v1 bindings and legacy string
`coverage` remain valid.
