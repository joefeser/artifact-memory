# Contributing

Artifact Memory is contract-first. Begin substantial changes with an issue or
design discussion so identity, compatibility, security, and extension
boundaries are understood before implementation.

## Use an issue when

- the outcome is bounded and acceptance criteria are known;
- a schema, fixture, CLI behavior, or adapter can be implemented and tested;
- a defect has a reproducible input and expected result.

## Use a discussion when

- terminology or authority boundaries remain unsettled;
- multiple compatible designs deserve comparison;
- a choice affects future interoperability;
- the question is exploratory rather than immediately actionable.

## Pull requests

- Use synthetic data only.
- Link the issue or decision being implemented.
- Explain compatibility and security implications.
- Add focused validation and conformance fixtures.
- Do not commit generated indexes unless a fixture explicitly requires them.
- Do not introduce private vault assumptions into public contracts.

By contributing, you agree that your contributions are licensed under the
Apache License 2.0.

## Branch and review policy

Work starts from `dev` in a fresh issue-linked `codex/` branch and worktree.
Pull requests target `dev` during incubation. Do not work directly on `main`,
force-push, squash, manually retag review bots, or merge a substantive change
without the repository ACK lane. Required Codex and Qodo reviews are a batch;
partial findings are not patch authority. Main and release promotion require a
separate human-mediated pull request.

Before creating a worktree, run the ACK worktree collision check described in
the repository coordinator handoff. Before requesting merge readiness, run the
repo-local `agent-control pr-loop` command and preserve its exact-head result.

The reference package currently uses only the Python standard library. New
dependencies must be justified in the issue or decision record, use a lockfile
when appropriate, and be covered by reproducible CI and provenance notes.
