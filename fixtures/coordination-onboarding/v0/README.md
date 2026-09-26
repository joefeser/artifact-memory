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
