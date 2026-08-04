# v0 canonical JSON, record identity, and revisions

Status: normative for `artifact-memory/*/v0` and `v1` digest inputs

Artifact Memory uses two identities for canonical records. `record_id` is the
stable, human-readable, namespaced identity of the logical knowledge record.
`revision_digest` is the SHA-256 digest of one exact canonical record revision,
written as `sha-256:<lowercase-hex>`. Neither a Git commit, branch, SQLite row,
filename, timestamp, nor storage location is protocol identity.

## Canonical JSON profile

Canonical bytes are UTF-8 JSON with:

- object keys sorted by Unicode code point;
- array order preserved;
- no insignificant whitespace or trailing newline;
- lowercase JSON literals;
- strings emitted without Unicode normalization and with only JSON-required
  escaping;
- no duplicate object keys;
- integers restricted to `-9007199254740991` through
  `9007199254740991`, inclusive; and
- fractional, exponent-form, and non-finite numeric values unsupported in
  canonical digest inputs. Integer `-0` has the single canonical form `0`.

The numeric restriction is deliberate. V0 does not claim that language-default
floating-point renderers are interoperable. Schemas may use descriptive numbers
outside canonical identity surfaces, but such values cannot enter a v0 canonical
digest until a later numeric profile defines their representation.

An implementation must reject invalid UTF-8, duplicate keys, unpaired Unicode
surrogates, unsupported numbers, non-string object keys, and non-JSON runtime
values, including cyclic containers. The integer-zero normalization above is
the only numeric lexical normalization in this profile.

## Revision and supersession behavior

A draft may be edited under the same `record_id`; each edit has a different
computed digest. A draft digest is useful for optimistic comparison but is not
a promise that the draft will be retained. Once a revision is accepted or
sealed and exchanged, its canonical bytes are immutable. A correction creates
a new revision or a new logical record and preserves the predecessor reference.

Supersession does not overwrite history. A superseded revision remains
addressable by its `(record_id, revision_digest)` pair, and the replacement is
recorded separately. Lifecycle timestamps, when present in another contract,
are metadata and are not substituted for revision identity.

Knowledge-record v2 evolution may additionally bind explicit `supersedes`,
`disputes`, or `contradicts` relationships to the exact source records used by
a candidate. These relationships preserve history; WITS remains responsible for
meaning, owner approval, and conflict resolution.

Schema identifiers are stable strings of the form `artifact-memory/<name>/vN`.
Changing required fields, field meaning, canonical digest input, or fail-closed
behavior requires a new major contract identifier. Additive optional behavior
uses the extension rules and cannot redefine identity, sensitivity, or
authority.

The language-neutral vectors under `fixtures/synthetic/canonical/v1/` are the
normative byte and digest examples. They contain newly authored synthetic data.
