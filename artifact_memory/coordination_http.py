"""Bounded bearer transport for the WITS validation bridge.

Only ref-only retry state is durable here. Records stay in the local canonical
vault, and the existing projection writer runs after complete verification.
"""
from __future__ import annotations

import ipaddress
import time
from bisect import bisect_right
from copy import deepcopy
from http.client import HTTPException
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .canonical import CanonicalizationFailure, canonical_bytes
from .coordination_sync import (
    MAX_PAGE_BYTES, MAX_RECORD_BYTES, MAX_REQUEST_BYTES, MAX_SUBMITTED_RECORDS, MAX_NESTING_DEPTH,
    SYNC_RECEIPT_SCHEMA_ID, SyncFailure, _acknowledged_hub_state, _check_raw_depth,
    _load_record_paths, _pair_key, _advisory_lock, _read_local_regular_file,
    _record_files, _record_path, _request_bounds, _validated_pair_manifest, _walk_bounds,
    _validated_pull_response, _write_atomic, apply_pull_response,
    validate_sync_receipt,
)
from .schema_resources import core_schemas
from .validator import ValidationFailure, load_json_bytes, validate

ENDPOINT = "/api/agent/coordination/sync"
# WITS scans <=128 MiB /10,000 records, packing pages with a 1 MiB
# metadata reserve and <=1 MiB records. Exact task/receipt refs are <512
# bytes. A byte-full page therefore holds > (2 MiB - 538) bytes; fewer
# than 68 such pages plus at most 20 count-full pages and a tail suffice.
# 100 pages leaves slack, including repeated receipt/token metadata.
MAX_HTTP_PAGES = 100
MAX_EXCHANGE_BYTES = MAX_HTTP_PAGES * MAX_PAGE_BYTES


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer to a redirected endpoint.
        return None


def _endpoint(url: str, endpoint: str = ENDPOINT) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = parsed.hostname
    except ValueError as exc:
        raise SyncFailure("sync-http-url-invalid", "hub URL is invalid") from exc
    if (parsed.scheme not in {"http", "https"} or not host
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/", ENDPOINT, endpoint}
            or (port is not None and not 1 <= port <= 65535)):
        raise SyncFailure("sync-http-url-invalid", "hub URL must name the WITS coordination endpoint")
    if parsed.scheme == "http":
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "localhost"
        if not local:
            raise SyncFailure("sync-http-tls-required", "non-loopback hubs require HTTPS")
    return urlunsplit((parsed.scheme, parsed.netloc, endpoint, "", ""))


def _post_json(opener, url: str, bearer: str, payload: dict, deadline: float, *,
               statuses: tuple[int, ...] = (200,), response_limit: int | None = None,
               operation: str = "sync") -> tuple[int, Any]:
    response_limit = MAX_PAGE_BYTES if response_limit is None else response_limit
    raw = canonical_bytes(payload)
    if len(raw) > MAX_REQUEST_BYTES:
        raise SyncFailure("sync-request-too-large", "HTTP request exceeds the v0 byte limit")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SyncFailure(f"{operation}-http-timeout", "HTTP exchange deadline expired; outcome is unverified")
    request = Request(url, data=raw, method="POST", headers={
        "Authorization": f"Bearer {bearer}", "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with opener.open(request, timeout=min(20, remaining)) as response:
            if response.status not in statuses:
                raise SyncFailure(f"{operation}-http-status", "hub did not return a successful exchange")
            status = response.status
            chunks, size = [], 0
            while True:
                if time.monotonic() >= deadline:
                    raise SyncFailure(f"{operation}-http-timeout", "HTTP exchange deadline expired; outcome is unverified")
                chunk = response.read1(min(65_536, response_limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > response_limit:
                    raise SyncFailure(f"{operation}-page-too-large", "HTTP response exceeds the bounded page limit")
            raw_response = b"".join(chunks)
    except HTTPError as exc:
        # Do not surface untrusted error bodies, URLs, credentials, or topology.
        code = exc.code
        exc.close()
        kind = {401: "unauthenticated", 403: "unauthorized", 409: "conflict"}.get(code, "http-rejected") if operation == "claim" else "http-rejected"
        raise SyncFailure(f"{operation}-{kind}", f"hub rejected exchange (HTTP {code})") from None
    except (URLError, OSError, TimeoutError, HTTPException):
        raise SyncFailure(f"{operation}-http-unavailable", "HTTP outcome is unverified; retry only the same explicit reference or sync batch") from None
    if len(raw_response) > response_limit:
        raise SyncFailure(f"{operation}-page-too-large", "HTTP response exceeds the bounded page limit")
    try:
        _check_raw_depth(raw_response, max_depth=MAX_NESTING_DEPTH + 5)
        value = load_json_bytes(raw_response)
        canonical_bytes(value)
    except (ValidationFailure, RecursionError, CanonicalizationFailure):
        raise SyncFailure(f"{operation}-response-invalid", "hub returned invalid JSON; outcome is unverified") from None
    return status, value


def _exchange(opener, url: str, bearer: str, payload: dict, deadline: float) -> dict:
    _, value = _post_json(opener, url, bearer, payload, deadline)
    if not isinstance(value, dict) or set(value) != {"receipt", "pages", "record_pages"}:
        raise SyncFailure("sync-response-invalid", "hub returned an invalid exchange shape")
    return value


def _require_bearer(bearer: str | None) -> str:
    if not isinstance(bearer, str) or not bearer or len(bearer) > 16_384 or any(c.isspace() for c in bearer):
        raise SyncFailure("sync-http-bearer-required", "HTTP coordination requires a bearer credential")
    return bearer


def _binding(hub_id, principal_id, label_ref) -> dict:
    schema = core_schemas()[SYNC_RECEIPT_SCHEMA_ID]["properties"]
    values = {"hub_id": hub_id, "principal_id": principal_id, "access_label_ref": label_ref}
    try:
        for name, value in values.items():
            validate(value, schema[name])
    except ValidationFailure:
        raise SyncFailure("sync-http-binding-required", "HTTP sync requires a pinned hub, principal, and AccessLabel reference") from None
    return deepcopy(values)


def _batch(vault: Path, binding: dict) -> list:
    known, attempted, fresh_cursor, retry_cursor, retry_first = _acknowledged_hub_state(
        vault, binding["hub_id"], binding["principal_id"])
    known_paths = {_record_path(vault, {"record_id": key[0], "revision_digest": key[1]}) for key in known}
    paths = [p for p in _record_files(vault) if p not in known_paths]
    attempted_paths = {_record_path(vault, {"record_id": key[0], "revision_digest": key[1]}) for key in attempted}
    fresh = [p for p in paths if p not in attempted_paths]
    retry = [p for p in paths if p in attempted_paths]
    def rotate(items, cursor):
        if not cursor:
            return items
        split = bisect_right(items, _record_path(vault, {"record_id": cursor[0], "revision_digest": cursor[1]}))
        return items[split:] + items[:split]
    fresh, retry = rotate(fresh, fresh_cursor), rotate(retry, retry_cursor)
    ordered = retry + fresh if retry_first and retry and fresh else fresh + retry
    records = []
    request_bytes = len(canonical_bytes({"records": [], "page_token": None}))
    for item in ordered:
        if len(records) >= MAX_SUBMITTED_RECORDS:
            break
        if item.stat().st_size > MAX_RECORD_BYTES:
            raise SyncFailure("sync-record-too-large", "local record exceeds the v0 byte limit")
        loaded = _load_record_paths(vault, [item], maximum_bytes=MAX_RECORD_BYTES)[0]
        if len(loaded.raw) > MAX_RECORD_BYTES:
            raise SyncFailure("sync-record-too-large", "local record exceeds the v0 byte limit")
        contribution = len(canonical_bytes({"record_ref": loaded.record_ref, "record": loaded.record}))
        proposed_bytes = request_bytes + contribution + bool(records)
        if proposed_bytes > MAX_REQUEST_BYTES:
            if not records:
                raise SyncFailure("sync-request-too-large", "local record cannot fit an HTTP request")
            break
        records.append(loaded)
        request_bytes = proposed_bytes
    _request_bounds(records)
    return records


def sync_http(vault: Path, hub: str, *, bearer: str | None,
              expected_hub_id: str | None, expected_principal_id: str | None,
              expected_access_label_ref: dict | None, phase: str = "both",
              before_apply: Callable[[dict], None] | None = None) -> dict[str, Any]:
    if phase not in {"push", "pull", "both"}:
        raise SyncFailure("sync-phase-invalid", "sync phase must be push, pull, or both")
    url = _endpoint(hub)
    bearer = _require_bearer(bearer)
    binding = _binding(expected_hub_id, expected_principal_id, expected_access_label_ref)
    pending_path = vault / "generated" / "coordination-sync" / "http-pending.json"
    # This is a local crash-released transport lock; the server owns admission.
    with _advisory_lock(vault, "http-coordination-transport",
                       busy_code="sync-principal-busy",
                       busy_message="one HTTP sync is already in flight for this vault"):
        if pending_path.exists() or pending_path.is_symlink():
            if phase == "push":
                raise SyncFailure("sync-pending-reconciliation-required", "pull must reconcile the pending HTTP batch")
            if pending_path.lstat().st_size > MAX_REQUEST_BYTES:
                raise SyncFailure("sync-pending-binding-mismatch", "HTTP retry state exceeds its bound")
            raw = _read_local_regular_file(vault, pending_path,
                missing_code="sync-pending-missing", missing_message="HTTP retry state is unavailable",
                maximum_bytes=MAX_REQUEST_BYTES)
            if len(raw) > MAX_REQUEST_BYTES:
                raise SyncFailure("sync-pending-binding-mismatch", "HTTP retry state exceeds its bound")
            try:
                _check_raw_depth(raw)
                pending = load_json_bytes(raw)
                if (not isinstance(pending, dict) or set(pending) != {"schema_id", "binding", "request_refs"}
                        or pending["schema_id"] != "artifact-memory/http-coordination-pending/v0"
                        or pending["binding"] != binding):
                    raise ValueError()
                if not isinstance(pending["request_refs"], list) or len(pending["request_refs"]) > MAX_SUBMITTED_RECORDS:
                    raise ValueError()
                refs = _validated_pair_manifest(pending["request_refs"])
            except (ValueError, ValidationFailure, RecursionError):
                raise SyncFailure("sync-pending-binding-mismatch", "HTTP retry state does not match the configured binding") from None
            records = _load_record_paths(vault, [_record_path(vault, ref) for ref in refs], maximum_bytes=MAX_RECORD_BYTES)
        else:
            records = _batch(vault, binding) if phase in {"push", "both"} else []
            refs = [r.record_ref for r in records]
            if records:
                _write_atomic(vault, pending_path, canonical_bytes({
                    "schema_id": "artifact-memory/http-coordination-pending/v0",
                    "binding": binding, "request_refs": refs,
                }))
        _request_bounds(records)
        request = {"records": [{"record_ref": r.record_ref, "record": r.record} for r in records], "page_token": None}
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        deadline = time.monotonic() + 120
        pages, record_pages, seen_tokens = [], [], set()
        receipt = None
        total_bytes = 0
        while True:
            response = _exchange(opener, url, bearer, request, deadline)
            total_bytes += len(canonical_bytes(response))
            if total_bytes > MAX_EXCHANGE_BYTES:
                raise SyncFailure("sync-response-too-large", "HTTP exchange exceeds the v0 deployment bound")
            current = response["receipt"]
            if not isinstance(current, dict):
                raise SyncFailure("sync-response-invalid", "HTTP receipt must be an object")
            validate_sync_receipt(current)
            if any(current[name] != value for name, value in binding.items()):
                raise SyncFailure("sync-binding-mismatch", "HTTP receipt does not match the configured binding")
            if receipt is None:
                receipt = current
                if current["authorized_membership"]["page_count"] > MAX_HTTP_PAGES:
                    raise SyncFailure("sync-page-count-mismatch", "HTTP membership exceeds the v0 deployment bound")
                if {_pair_key(o["record_ref"]) for o in current["submission_outcomes"]} != {_pair_key(r) for r in refs}:
                    raise SyncFailure("sync-outcomes-invalid", "HTTP outcomes do not cover the exact submitted batch")
            elif current != receipt:
                raise SyncFailure("sync-page-receipt-mismatch", "HTTP continuation changed its receipt")
            if (not isinstance(response["pages"], list) or len(response["pages"]) != 1
                    or not isinstance(response["record_pages"], list) or len(response["record_pages"]) != 1):
                raise SyncFailure("sync-response-invalid", "HTTP response must contain one matching page")
            page = response["pages"][0]
            validate(page, core_schemas()["artifact-memory/coordination-authorized-membership-page/v0"])
            if page["page_index"] != len(pages):
                raise SyncFailure("sync-page-missing", "HTTP page sequence is incomplete")
            record_page = response["record_pages"][0]
            if not isinstance(record_page, list) or len(record_page) > 500:
                raise SyncFailure("sync-record-page-mismatch", "HTTP record page exceeds its bound")
            for record in record_page:
                _walk_bounds(record)
                if len(canonical_bytes(record)) > MAX_RECORD_BYTES:
                    raise SyncFailure("sync-record-too-large", "HTTP record exceeds the v0 byte limit")
            pages.append(page)
            record_pages.extend(response["record_pages"])
            token = page["next_token"]
            final = len(pages) == receipt["authorized_membership"]["page_count"]
            if final:
                if token is not None:
                    raise SyncFailure("sync-page-token-invalid", "final HTTP page has a continuation")
                break
            if not isinstance(token, str) or not token or len(token) > 500_000 or token in seen_tokens:
                raise SyncFailure("sync-page-token-invalid", "HTTP continuation is invalid or repeated")
            seen_tokens.add(token)
            request = {"records": [], "page_token": token}
        assembled = {"receipt": receipt, "pages": pages, "record_pages": record_pages}
        _validated_pull_response(assembled, opaque_tokens=True)
        if phase == "push":
            return {"outcome": "complete", "phase": phase, "submission_outcomes": receipt["submission_outcomes"], "receipt": receipt}
        result = apply_pull_response(vault, assembled, _before_apply=before_apply, opaque_tokens=True)
        if pending_path.exists():
            pending_path.unlink()
        result.update(phase=phase, submission_outcomes=receipt["submission_outcomes"])
        return result
