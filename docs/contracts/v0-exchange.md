# v0 bounded knowledge exchange

An exchange envelope carries bounded record revisions and artifact references
with an audience, correlation ID, expiry, handling policy, and explicit
no-authority boundary. Admission is receiver-owned and produces typed truth;
replays are idempotently reported as duplicates, while expired, unsupported,
empty, and partially resolved input remains explicit.

Exchange is not a WITS/HACP Task Packet, Route Task, owner grant, execution
authorization, or Codex continuation payload. A receiver may later create an
authority-bearing task through its own authenticated WITS process, but that
authority is not hidden in this envelope or receipt.
