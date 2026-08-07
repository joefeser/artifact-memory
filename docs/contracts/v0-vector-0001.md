# v0 vector 0001: one exact file

This is the one synthetic vector requested by issue #12 for the first slice.
It deliberately covers one file and does not claim to define the complete
cross-platform tree-manifest algorithm.

The exact content bytes are the UTF-8 sequence:

```text
Artifact Memory synthetic order v0
```

The vector's content digest is SHA-256 over those bytes. Its candidate tree
leaf serialization is the UTF-8 line
`file<TAB>orders.txt<TAB><content-digest><TAB>35<LF>`, with the literal tab and
line-feed separators shown by the fixture's escaped `leaf_serialization`.
The tree digest is SHA-256 over that leaf serialization. Future #13/#14
runtime and validator work must either implement this exact vector or report a
typed unsupported outcome; it must not silently substitute a different tree
identity algorithm.
