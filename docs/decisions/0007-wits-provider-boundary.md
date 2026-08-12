# Decision 0007: keep WITS meaning and authority behind an opaque process boundary

Status: superseded in part by Decision 0020. The opaque process boundary and
authority restrictions remain accepted; Decision 0020 corrects the ownership
language and defines the compatibility interpretation of `owner-meaning`.

Artifact Memory may bind an opaque WITS owner-meaning, decision, readiness, or
ambiguity projection to exact canonical record revisions. It may preserve that
projection as content, reference it from an informational context pack, and
carry the reference through generated indexes, backup, and restore.

Artifact Memory does not own or interpret the projected meaning. WITS memory
cards and fresh-context packets remain WITS restart/projection records. HACP
Task Packets and Route Tasks remain separate authority-bearing WITS contracts;
a Codex continuation payload remains subordinate to those contracts.

The first supported contract anchor is WITS commit
`d675ba6d632dc03826f27940014d4cd672f7d910`. WITS is BSL 1.1, changing to
Apache-2.0 on 2030-01-01. The Apache-2.0 Artifact Memory repository records
only compatible behavior, opaque references, exact contract paths, and license
provenance. It does not copy WITS code or schema text.

Nested authority-shaped fields fail closed. Portable knowledge, provider
responses, records, and context packs never authorize WITS invocation, task
creation, routing, execution, mutation, credentials, spending, merge,
deployment, or declassification.

Residual limitation: the v0 fixture uses a synthetic opaque WITS response. It
proves Artifact Memory conformance, not a live independent WITS implementation.
