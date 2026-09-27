# Synthetic coordination freshness fixture

This fixture contains only synthetic repository history and coordination
records. It proves that a supported coordination freshness extension is
evaluated against an exact onboarded repository HEAD, a divergent commit is
marked `stale-verify`, an ancestor is marked `current`, unknown optional
extensions remain opaque, and unknown required or top-level freshness fields
fail closed.

Run:

```sh
python3 scripts/run_coordination_freshness_conformance.py --check
```
