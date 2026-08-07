# Portable manifest vectors v1

`vectors.json` is a runner-neutral synthetic fixture for the narrow v0
ordinary-tree profile. Each positive case describes the same logical entries
under Windows, macOS, and Linux mount roots in deliberately different
observation orders. The mount roots are test inputs and never enter identity.

The negative cases require distinct collision, unsupported, and partial
outcomes. `container_boundary` proves only that exact container bytes and an
extracted logical tree have separate identities; issue #25 owns extraction
safety.

`expected-receipt.json` and `receipt.md` are checked machine- and
human-readable evidence. All contents are newly authored synthetic data.
