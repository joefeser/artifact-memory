# v0 custody receipt

A backup receipt proves encrypted bytes and a source manifest. A custody
receipt separately records the intended local or off-machine endpoint,
authorization state, key-recovery state, and restore-test cadence. It never
copies backup bytes and never turns an endpoint reference into authorization.

An unapproved off-machine endpoint must remain `not-authorized`; the receipt is
not evidence that a replica exists. Durable key recovery and test cadence are
owner policy and remain external to the encrypted backup payload.
