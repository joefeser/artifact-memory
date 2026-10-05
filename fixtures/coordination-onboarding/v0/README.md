# Synthetic AM-9 coordination onboarding fixture

The acceptance runner creates disposable Git repositories, local vaults, and
provider-free hubs from the public synthetic coordination records. No generated
vault, repository path, hub configuration, session transcript, or AccessLabel
body is retained in this fixture.

Run:

```sh
python3 scripts/run_coordination_onboarding_conformance.py --check
```

The receipt proves fresh-repository bootstrap, preservation of an existing
pair, byte-identical rerun, typed un-onboarded failure, and the informational-
only authority boundary. Session-ledger ingestion remains AM-1; queue and
acceptance-command rendering remain AM-5.

Focused unit regressions additionally prove serialized concurrent onboarding,
recovery after interruption at every publication output, strict persisted-link
loading, bare-repository rejection, and fail-closed unsupported identity
creation when safe parent-directory primitives are unavailable.
The transaction-boundary regression additionally submits one unsynced
synthetic record, interrupts immediately after its successful sync, and proves
retry reuses the exact authenticated receipt rather than losing its admission
outcome or colliding on the observation timestamp.

The interruption matrix also covers failure after push but before pull,
failure after marker advancement but before pending-outcome consumption, and a
later successful pull advancing the current marker before onboarding resumes.
Each path recovers from the attempt-specific bounded response checkpoint.
The focused runtime regressions also prove that a rejected first-sync attempt
is retained under its digest, a corrected prerequisite can succeed through a
fresh attempt, and an interruption after failed-evidence archival completes
the retirement before retrying.
