# Decision 0011: separate logical endpoints from discovery and local resolution

Status: accepted
Date: 2026-08-01

Issue: #9.

Artifact Memory uses portable `endpoint://` identities and relative paths in
durable observations. Storage capabilities are endpoint contract facts.
Discovery evidence is time-bounded evidence about a local match. Absolute
roots belong only to machine-local resolver configuration.

This separation lets equivalent macOS, Windows, and Linux mount layouts refer
to the same observed bytes without making any platform spelling canonical.
Discovery evidence does not establish endpoint identity, and a successful
resolution grants no access or mutation authority.

V0 keeps resolver configuration outside portable records. A future portable
resolver format would need a new contract proving that it cannot disclose
machine topology, credentials, or bearer URLs.
