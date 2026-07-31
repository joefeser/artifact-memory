# v0 normalized manifest profile

The supported v0 tree profile compares normalized relative paths
case-sensitively by Unicode code point, uses `/` separators, and hashes UTF-8
canonical leaf lines. Ordinary files and directories are supported. Symlinks,
special files, unreadable entries, and portability-affecting case-folded
collisions are explicit unsupported or partial outcomes.

Container bytes and an extracted tree are distinct content/tree claims even
when they describe related material. Unicode normalization, hard links, sparse
files, alternate data streams, extended attributes, and platform metadata are
not silently equated by this profile.

Manifest consumers fail closed unless entries are unique and sorted, paths are
normalized UTF-8 relative paths, every nested entry has an admitted directory
parent, file entries carry byte size and content digest, directory entries do
not carry file fields, and both manifest and tree identities match the
canonical body. Partial manifests remain useful bounded evidence, but a diff
that consumes one is explicitly partial.
