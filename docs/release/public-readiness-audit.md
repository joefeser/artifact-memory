# Public-readiness audit record

This record is a repeatable audit procedure and current evidence summary. It
does not itself change repository visibility or grant publication authority.

## Evidence collected on 2026-07-30

- Reachable branches were reviewed: `main`, `dev`, and the three open feature
  branches for PRs #34, #38, and #40. No tags exist yet.
- The governance history scanner reported a pass over 24 commits, 362
  historical objects, and 136 current paths.
- Public JSON syntax validation reported a pass for 55 schema and synthetic
  fixture files.
- The platform matrix completed successfully on real macOS, Linux, and
  Windows runners. Receipts contain no host paths, usernames, or mount points.
- The full provider-free test suite passes with 42 tests.
- The repository license, security policy, contribution guidance, synthetic
  fixture policy, and support limitations are present.

The scanner is a high-confidence guardrail, not proof that protected material
could never exist. Human review remains required for every reachable branch,
tag, issue, pull request, Actions log, release artifact, and repository
setting before visibility changes.

## Required owner-controlled actions

- review and approve the open PRs through the authenticated review process;
- inspect repository history and Actions artifacts after the final merge;
- restore or verify branch protection and push rules;
- configure and use the owner's signing key for a release tag;
- change visibility only after the anonymous public-clone checklist passes.

## Anonymous clone checklist

From a machine with no repository credentials or vault mounts:

```shell
git clone <public-repository-url> artifact-memory-public-check
cd artifact-memory-public-check
git fsck --full --no-reflogs
python3 -m unittest discover -s tests -v
python3 -m artifact_memory version --json
```

Then inspect the clone for real paths, credentials, customer material, raw
task transcripts, generated-only knowledge, and unexpected network or
mutation behavior. Record the source commit and all command results in the
release review.
