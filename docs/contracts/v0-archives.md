# v0 archive and extracted-tree boundary

An archive container is an independently hashed content object. An extracted
tree receives a separate normalized manifest/tree digest. The reference ZIP
inspector rejects or reports path traversal, duplicate/case collisions,
encrypted entries, corruption, and decompression-limit conditions explicitly;
it does not execute entries or silently equate container and tree identity.
