# Aggregate synthetic conformance fixture v1

`manifest.json` is the language-neutral inventory for one representative case
in each required class: valid, invalid, equivalent, collision, and unsupported.
Every input is a repository-relative reference bound to its exact SHA-256
digest. `expected-results.json` records outcomes and JSON Pointer assertions
without depending on a Python exception type or test framework.

All cases are newly authored synthetic data. They are not copied, sampled, or
lightly redacted from a customer, private vault, production system, browser
session, or raw task transcript.

The aggregate runner proves only the operations named by this fixture version.
It does not make a general cross-platform claim, establish authenticity, or
grant access, disclosure, mutation, execution, or declassification authority.
