# Decision 0001: Public-safe governance and review lane

Status: accepted
Date: 2026-07-30
Linked issue: #32

## Context

Artifact Memory is private incubation but is operated as public-safe from its
first commit. GitHub secret scanning, private vulnerability reporting,
repository rulesets, and branch protection are unavailable on the current
private personal-repository plan. Local and CI checks therefore need to make
the public/private boundary explicit without pretending to replace GitHub
security features.

## Decision

- Use a full-history checkout in CI and run `scripts/public_safety_check.py`.
- Fail closed on forbidden vault, private-record, artifact, object, quarantine,
  credential, database, and local-state paths.
- Fail closed on high-confidence private-key, bearer-token, and common provider
  token patterns. A clean result is not a complete secret-discovery guarantee.
- Keep canonical records and schemas as the future source of truth; generated
  indexes and local state are rejected by path policy.
- Use `.agent-control/lanes/pr-review-loop.yaml` as the repository review lane.
  Codex and Qodo are required reviewers and are batched before patch authority.
  Qodo is never manually retagged by ACK.
- Permit unattended review-loop forward motion only for `dev` and explicitly
  configured integration branches. Main, master, and release branches require
  human-mediated promotion and use merge commits rather than squash by default.
- Keep auto-merge disabled in the lane. The #32 PR is the bootstrap exception:
  it may use one exact-head Codex review and requires Joe for initial merge.

## Consequences

This provides repeatable local/CI evidence and a durable review policy while
GitHub-hosted protections are unavailable. The scanner intentionally favors
false positives over silent publication risk and must be extended with each
new contract or artifact class. When the repository becomes public, enable
available GitHub security features, re-establish branch rules, and rerun the
full history audit before accepting public contributions.

## Nonclaims

The checks do not inspect private vaults, decrypt archives, prove semantic
safety, authorize adapter execution, or establish that a clean scan proves the
absence of every secret. GitHub secret scanning and private vulnerability
reporting are not active for the current repository configuration.
