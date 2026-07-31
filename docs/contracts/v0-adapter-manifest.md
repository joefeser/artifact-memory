# v0 adapter manifests

An adapter manifest declares identity/version, supported contracts, filesystem,
network, credential, mutation, and provider-output read capabilities, input and
output schema references, and determinism. It explicitly states that record
contents cannot authorize execution. Adapter receipts are machine-readable and
do not imply execution, mutation, credentials, or approval.

The TraceMap binding manifest is read-only, network-free, credential-free, and
explicitly authorized outside portable records. The independent synthetic
reference manifest proves the minimum machinery without discovery, dynamic
loading, marketplace behavior, or an isolation runtime.
