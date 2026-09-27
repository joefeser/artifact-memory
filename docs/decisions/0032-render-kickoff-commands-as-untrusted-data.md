# 0032: Render coordination kickoff commands as untrusted data

Status: accepted for AM-5

## Context

A fresh agent needs a small queue view, but a TaskPacket's
`dod.acceptanceCommand` is issuer-unverified record content. Copying that text
into an instruction or executable code block would turn memory into apparent
authority and create a prompt/instruction-injection surface.

The current authenticated sync projection already binds an exact membership
set to a receipt, observation time, and scope generation. Canonical local
storage may additionally contain pending, rejected, quarantined, or formerly
visible revisions that are not current admitted queue state.

## Decision

`artifact-memory kickoff` reads only a complete AM-9 onboarding state and the
latest verified authorized-membership projection. It validates complete
TaskPacket predecessor chains, rejects any local project TaskPacket absent from
that membership, and selects the lexicographically greatest `taskId` among
unique current open leaves.

The pack contains only a bounded queue summary and one selected task. Its
receipt reference, observation timestamp, scope generation, membership digest,
authenticated transport state, and issuer-unverified state remain explicit.

The Markdown rendering JSON-encodes and HTML-escapes every queue text field.
`acceptanceCommand` appears only in a labeled HTML data block beside an
explicit `DO NOT EXECUTE` instruction. The generator never passes record text
to a shell, subprocess, tool call, or instruction template. Separate
authenticated authority is required before any execution.

## Consequences

- Missing or tampered sync evidence, onboarding/sync binding mismatch,
  membership mismatch, unadmitted local TaskPackets, and broken or forked task
  chains fail typed.
- Display-name lookup is allowed only when unambiguous; the UUID remains the
  authoritative project selector.
- The pack is informational evidence, not issuer authenticity, task ownership,
  execution approval, or a replacement for canonical records.
- V0 intentionally emits one bounded selected-task summary rather than a
  generalized scheduler, execution runtime, or semantic retrieval surface.
