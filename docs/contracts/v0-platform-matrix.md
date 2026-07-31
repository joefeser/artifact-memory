# v0 platform conformance matrix

The matrix probe records sanitized observations from an actual runner. It
never records temporary paths, hostnames, usernames, mount points, or file
contents. Each runner reports its runtime family and the observed behavior for
case sensitivity, Unicode names, and link creation.

The v0 comparison profile remains explicit: relative paths use `/`, compare
case-sensitively by Unicode code point, and do not include timestamps or mount
layout in tree identity. Symlinks are reported as unsupported by the v0 scan,
even when the host can create them. A probe result describes only its runner;
it does not establish behavior for another platform.

The required matrix is macOS, Linux, and Windows. The committed synthetic
fixture names the cases; the sanitized receipts must be produced by actual
runners before cross-platform support is claimed.
