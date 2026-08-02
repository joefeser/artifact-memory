# v0 storage endpoints and location observations

This contract represents where exact bytes were observed without turning a
mount point, drive letter, hostname, provider URL, bearer URL, filename, or
resolver root into durable identity.

## Logical identity

- `artifact://<namespace>/<name>` identifies one logical artifact. It does not
  identify bytes or a location.
- `content://sha-256/<lowercase-hex>` identifies exact bytes. It does not
  identify an artifact or a location.
- `endpoint://<namespace>/<name>` identifies a logical storage endpoint. A
  single-segment endpoint remains valid for the approved custody endpoint.
- A location uses a slash-delimited relative path with no leading slash,
  backslash, parent segment, URI scheme, query, or fragment.

These identifiers are case-sensitive. V0 does not infer aliases or normalize
Unicode. Artifact identity, content identity, endpoint identity, and relative
path remain separate fields.

## Endpoint capability and discovery

`storage-endpoint/v1` declares a logical endpoint's storage class and explicit
read, write, list, verify, and delete capabilities. Capabilities describe what
an adapter may support; they grant no authorization.

`endpoint-discovery-evidence/v1` records time-bounded evidence that local
discovery matched, failed to match, or could not inspect an endpoint. Its
digest binds sanitized evidence, not a hostname or mount root. Discovery
evidence can support a resolver decision but can never create or replace the
logical endpoint identity.

## Location observations

`location-observation/v2` binds one logical artifact and one exact content
object to an endpoint-relative path at a stated time. Presence and verification
are separate facts. `present`, `absent`, and `unavailable` do not silently imply
content integrity. Content verification is valid only when bytes were present.

Observations grant no access, mutation, disclosure, declassification, or
execution authority. A later observation does not erase an earlier one.

## Local resolver boundary

`resolver-config/v1` is machine-local configuration and is not a portable
record. It may contain an absolute local root because resolution cannot occur
without one. It must never be exchanged as canonical knowledge, included in a
  context pack, or copied into a portable receipt. Resolver configuration has
no credential or bearer-URL fields; adapters obtain authentication through a
separate authorized local mechanism.

The synthetic conformance fixture creates ephemeral local roots representing
macOS volume, Windows drive, and Linux filesystem-mount layouts. All three
resolve the same endpoint and relative path. The checked receipt retains only
the logical references and sanitized outcomes.

## Compatibility and security

`location-observation/v1` remains readable and is not reinterpreted. Writers
use v2. Unknown fields fail closed. Future capability or observation semantics
require a new schema version. Portable records are safe to exchange only after
their ordinary classification and declassification policy has also passed;
location portability is not a disclosure decision.
