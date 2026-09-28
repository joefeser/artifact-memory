"""Command-line entrypoint for the provider-free v0 shell."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import CONTRACT_VERSION, __version__
from .archive import validate_archive_receipt
from .codex_history import (
    import_task_export,
    sanitize_private_import_receipt,
    write_import_bundle,
)
from .context import (
    CONTEXT_READ_SCHEMAS,
    ContextFailure,
    build_selection_policy,
    export_context,
    validate_context_pack,
)
from .coordination import validate_coordination_files
from .coordination_claim import claim_http
from .coordination_context import (
    CONTEXT_PACK_SCHEMA_ID as COORDINATION_CONTEXT_PACK_SCHEMA_ID,
    open_coordination_context_pack,
    validate_coordination_context_pack,
)
from .coordination_kickoff import (
    KICKOFF_PACK_SCHEMA_IDS,
    build_kickoff_pack,
    render_kickoff_prompt,
    validate_kickoff_pack,
)
from .coordination_onboarding import (
    BOOTSTRAP_PACK_SCHEMA_ID,
    BOOTSTRAP_RECEIPT_SCHEMA_ID,
    onboard_project,
    require_repo_onboarding,
    validate_bootstrap_pack,
    validate_bootstrap_receipt,
    validate_repo_bound_append,
)
from .coordination_sync import (
    SYNC_RECEIPT_SCHEMA_ID,
    SyncFailure,
    append_local_coordination_record,
    load_local_coordination_record,
    sync as sync_coordination,
    validate_sync_receipt,
)
from .projection import project_records, records_with_provenance, related_records, search_records, search_receipt
from .release import (
    render_release_candidate_verification_receipt,
    validate_release_manifest,
    validate_release_candidate_verification_receipt,
    verify_checked_out_release_candidate,
)
from .release_preparation import (
    render_release_candidate_preparation_receipt,
    validate_release_preparation_receipt,
    validate_release_candidate_preparation_receipt,
)
from .repo_identity import validate_repo_bound_coordination_files
from .scan import diff_manifests, scan_path, verify_path
from .schema_resources import core_schemas
from .session_ledger import import_session_ledger
from .validator import ValidationFailure, load_json, validate

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_UNSUPPORTED = 3


def _schemas() -> dict[str, dict[str, object]]:
    return core_schemas()


def _receipt(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="artifact-memory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    record_commands = {
        "validate": (
            "validate JSON syntax, duplicate keys, schema constraints, and supported "
            "semantic rules (including release-manifest releasability and context-pack "
            "identity/budget binding); validation "
            "does not verify authenticity or accept release evidence"
        ),
        "inspect": "report schema and field names without validating record semantics",
    }
    for name, description in record_commands.items():
        command = subparsers.add_parser(name, help=description, description=description)
        command.add_argument("record", type=Path)
        command.add_argument("--schema", type=Path)
        command.add_argument("--json", action="store_true", dest="as_json")
    records = subparsers.add_parser("records", help="operate on a coordination record set")
    records_commands = records.add_subparsers(dest="records_command", required=True)
    records_validate = records_commands.add_parser(
        "validate",
        help="validate strict coordination records and their exact in-batch revision bindings",
    )
    records_validate.add_argument("records", type=Path, nargs="+")
    records_validate.add_argument("--json", action="store_true", dest="as_json")
    repo = subparsers.add_parser(
        "repo", help="validate repository identities and project-bound records"
    )
    repo_commands = repo.add_subparsers(dest="repo_command", required=True)
    repo_validate = repo_commands.add_parser(
        "validate",
        help="validate strict repo manifests and coordination project UUID references",
    )
    repo_validate.add_argument("roots", type=Path, nargs="+")
    repo_validate.add_argument(
        "--records", type=Path, nargs="+", required=True
    )
    repo_validate.add_argument("--json", action="store_true", dest="as_json")
    record = subparsers.add_parser(
        "record", help="append one coordination record to a local vault"
    )
    record_commands = record.add_subparsers(dest="record_command", required=True)
    record_append = record_commands.add_parser(
        "append",
        help="append locally without contacting a coordination hub",
    )
    record_append.add_argument("record", type=Path)
    record_append.add_argument("--vault", required=True, type=Path)
    record_append.add_argument(
        "--repo",
        type=Path,
        help="require committed AM-9 onboarding for this repo-bound append",
    )
    record_append.add_argument("--json", action="store_true", dest="as_json")
    sync_parser = subparsers.add_parser(
        "sync",
        help="sync coordination through a local path or WITS HTTP hub",
    )
    sync_parser.add_argument("--vault", required=True, type=Path)
    sync_parser.add_argument("--hub", required=True)
    sync_parser.add_argument("--hub-id", help="expected logical HTTP hub identity")
    sync_parser.add_argument("--principal-id", help="expected bearer-bound HTTP principal")
    sync_parser.add_argument("--access-label-ref", help="expected HTTP AccessLabel reference as JSON")
    sync_parser.add_argument("--bearer-env", default="ARTIFACT_MEMORY_COORDINATION_BEARER",
                             help="environment variable containing the HTTP bearer; never put credentials in arguments")
    sync_parser.add_argument(
        "--repo",
        type=Path,
        help="require committed AM-9 onboarding for this repo-bound sync",
    )
    sync_parser.add_argument(
        "--session-id",
        help="opaque authenticated-session handle resolved by the hub",
    )
    sync_parser.add_argument("--phase", choices=["push", "pull", "both"], default="both")
    sync_parser.add_argument("--completed-at", help="completion time for the local-path adapter; HTTP uses server time")
    sync_parser.add_argument("--json", action="store_true", dest="as_json")
    claim_parser = subparsers.add_parser("claim", help="claim one exact assigned task through the WITS HTTP hub; no execution")
    claim_parser.add_argument("--vault", required=True, type=Path)
    claim_parser.add_argument("--hub", required=True)
    claim_parser.add_argument("--project-id", required=True)
    claim_parser.add_argument("--task-ref", required=True, help="exact original open TaskPacket reference as JSON")
    claim_parser.add_argument("--hub-id", required=True)
    claim_parser.add_argument("--principal-id", required=True)
    claim_parser.add_argument("--access-label-ref", required=True, help="exact credential-bound AccessLabel reference as JSON")
    claim_parser.add_argument("--bearer-env", default="ARTIFACT_MEMORY_COORDINATION_BEARER")
    claim_parser.add_argument("--json", action="store_true", dest="as_json")
    onboard = subparsers.add_parser(
        "onboard",
        help="bind one Git repo to an externally administered coordination project",
    )
    onboard.add_argument("repo", type=Path)
    onboard.add_argument("--vault", required=True, type=Path)
    onboard.add_argument("--hub", required=True, type=Path)
    onboard.add_argument("--session-id", required=True)
    onboard.add_argument("--completed-at", required=True)
    onboard.add_argument("--project-id")
    onboard.add_argument("--human-name")
    onboard.add_argument("--json", action="store_true", dest="as_json")
    kickoff = subparsers.add_parser(
        "kickoff",
        help="emit bounded informational startup context from verified queue evidence",
    )
    kickoff.add_argument("--project", required=True)
    kickoff.add_argument("--vault", required=True, type=Path)
    kickoff.add_argument(
        "--repo",
        type=Path,
        help="evaluate the supported coordination freshness extension against this onboarded repo",
    )
    kickoff.add_argument("--json", action="store_true", dest="as_json")
    coordination_context = subparsers.add_parser(
        "coordination-context",
        help="export context from the latest verified authorized coordination projection",
    )
    coordination_context.add_argument("--vault", required=True, type=Path)
    coordination_context.add_argument("--json", action="store_true", dest="as_json")
    session_ledger = subparsers.add_parser(
        "import-session-ledger",
        help="import bounded ISO-dated done-log entries into a private vault",
    )
    session_ledger.add_argument("done_log", type=Path)
    session_ledger.add_argument("--vault", required=True, type=Path)
    session_ledger.add_argument("--dry-run", action="store_true")
    session_ledger.add_argument("--json", action="store_true", dest="as_json")
    scan = subparsers.add_parser("scan")
    scan.add_argument("root", type=Path)
    scan.add_argument("--out", type=Path)
    scan.add_argument("--json", action="store_true", dest="as_json")
    verify = subparsers.add_parser("verify")
    verify.add_argument("root", type=Path)
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--policy", type=Path, help="exact digest-bound scan policy used by the manifest")
    verify.add_argument("--json", action="store_true", dest="as_json")
    diff = subparsers.add_parser("diff")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    diff.add_argument("--json", action="store_true", dest="as_json")
    project = subparsers.add_parser("project")
    project.add_argument("records", type=Path, nargs="+")
    project.add_argument("--out", required=True, type=Path)
    project.add_argument("--json", action="store_true", dest="as_json")
    search = subparsers.add_parser("search")
    search.add_argument("index", type=Path)
    search.add_argument("query")
    search.add_argument("--literal", action="store_true", help="treat the query as one literal query string instead of raw FTS5 syntax")
    search.add_argument("--exclude-superseded", action="store_true", dest="exclude_superseded", help="drop matches whose record lifecycle is superseded")
    search.add_argument("--rank", action="store_true", help="order results by bm25 relevance with a record-id tiebreak; corpus-dependent, never authoritative")
    search.add_argument("--json", action="store_true", dest="as_json")
    search_receipt_parser = subparsers.add_parser("search-receipt")
    search_receipt_parser.add_argument("index", type=Path)
    search_receipt_parser.add_argument("query")
    search_receipt_parser.add_argument("--literal", action="store_true", help="treat the query as one literal query string instead of raw FTS5 syntax")
    search_receipt_parser.add_argument("--exclude-superseded", action="store_true", dest="exclude_superseded", help="drop matches whose record lifecycle is superseded")
    search_receipt_parser.add_argument("--rank", action="store_true", help="order results by bm25 relevance with a record-id tiebreak; corpus-dependent, never authoritative")
    search_receipt_parser.add_argument("--json", action="store_true", dest="as_json")
    related = subparsers.add_parser("related")
    related.add_argument("index", type=Path)
    related.add_argument("record_id")
    related.add_argument("--json", action="store_true", dest="as_json")
    provenance = subparsers.add_parser("provenance")
    provenance.add_argument("index", type=Path)
    provenance.add_argument("source_ref")
    provenance.add_argument("--json", action="store_true", dest="as_json")
    context = subparsers.add_parser("context")
    context.add_argument("records", type=Path, nargs="+")
    context.add_argument("--evidence", type=Path)
    context.add_argument("--out", type=Path)
    context.add_argument("--allow-sensitivity", choices=["public", "private", "restricted"], default="public")
    context.add_argument("--max-bytes", type=int, default=32_768)
    context.add_argument("--selected-at", required=True, help="whole-second UTC selection time")
    context.add_argument("--freshness-basis", required=True, help="operator assertion or receipt reference")
    context.add_argument("--authorize-evidence", action="append", nargs=2, metavar=("PROVIDER_ID", "PROVIDER_RECORD_ID"), default=[], dest="authorized_evidence")
    context.add_argument("--support-required-extension", action="append", nargs=2, metavar=("IDENTIFIER", "VERSION"), default=[], dest="supported_required_extensions")
    context.add_argument(
        "--support-context-schema",
        action="append",
        choices=[
            "artifact-memory/context-pack/v2",
            "artifact-memory/context-pack/v3",
            "artifact-memory/context-pack/v4",
        ],
        default=[],
        dest="supported_context_schema_ids",
        help="negotiated context-pack schema; repeat for multiple supported versions",
    )
    context.add_argument("--json", action="store_true", dest="as_json")
    codex_history = subparsers.add_parser("import-codex-history")
    codex_history.add_argument("task_export", type=Path)
    codex_history.add_argument("policy", type=Path)
    codex_history.add_argument("--out", required=True, type=Path)
    codex_history.add_argument("--json", action="store_true", dest="as_json")
    dogfood_receipt = subparsers.add_parser("codex-history-dogfood-receipt")
    dogfood_receipt.add_argument("private_declassification_receipt", type=Path)
    dogfood_receipt.add_argument("--performed-at", required=True)
    dogfood_receipt.add_argument("--json", action="store_true", dest="as_json")
    version = subparsers.add_parser("version")
    version.add_argument("--json", action="store_true", dest="as_json")
    release_candidate = subparsers.add_parser("verify-release-candidate")
    release_candidate.add_argument("manifest", type=Path)
    release_candidate.add_argument("--tag", required=True)
    release_candidate.add_argument("--repo", required=True, type=Path)
    release_candidate.add_argument(
        "--asset-dir",
        type=Path,
        help="explicit staged-asset directory required by asset-aware v2 verification",
    )
    release_candidate.add_argument("--owner-fingerprint", required=True)
    release_candidate.add_argument(
        "--isolated-checkout",
        action="store_true",
        help="assert exclusive control of this fresh checkout during verification",
    )
    release_candidate.add_argument("--json", action="store_true", dest="as_json")
    release_receipt = subparsers.add_parser("validate-release-candidate-receipt")
    release_receipt.add_argument("receipt", type=Path)
    release_receipt.add_argument("--json", action="store_true", dest="as_json")
    preparation_receipt = subparsers.add_parser(
        "validate-release-candidate-preparation-receipt"
    )
    preparation_receipt.add_argument("receipt", type=Path)
    preparation_receipt.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if args.command == "record" and args.record_command == "append":
        try:
            link = None
            if args.repo is not None:
                link = require_repo_onboarding(args.repo, args.vault)
            candidate = load_local_coordination_record(args.record)
            if link is not None:
                candidate = validate_repo_bound_append(link, candidate)
            result = append_local_coordination_record(args.vault, candidate)
        except (SyncFailure, ValidationFailure, OSError, RecursionError) as exc:
            _receipt(
                {
                    "outcome": "rejected",
                    "diagnostics": [
                        {
                            "code": getattr(exc, "code", "local-append-storage-unavailable"),
                            "message": getattr(
                                exc,
                                "message",
                                "local coordination storage is unavailable",
                            ),
                        }
                    ],
                },
                args.as_json,
            )
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK

    if args.command == "records" and args.records_command == "validate":
        try:
            result = validate_coordination_files(args.records)
        except ValidationFailure as exc:
            _receipt(
                {
                    "valid": False,
                    "outcome": "rejected",
                    "diagnostics": [
                        {"code": exc.code, "path": exc.path, "message": exc.message}
                    ],
                },
                args.as_json,
            )
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK

    if args.command == "repo" and args.repo_command == "validate":
        try:
            result = validate_repo_bound_coordination_files(
                args.records, args.roots
            )
        except ValidationFailure as exc:
            _receipt(
                {
                    "valid": False,
                    "outcome": "rejected",
                    "diagnostics": [
                        {"code": exc.code, "path": exc.path, "message": exc.message}
                    ],
                },
                args.as_json,
            )
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK

    if args.command == "claim":
        try:
            try:
                task_ref = json.loads(args.task_ref)
                label_ref = json.loads(args.access_label_ref)
            except ValueError:
                raise SyncFailure("claim-binding-invalid", "task-ref and access-label-ref must be JSON references") from None
            result = claim_http(args.vault, args.hub, task_ref=task_ref, project_id=args.project_id,
                bearer=os.environ.get(args.bearer_env), expected_hub_id=args.hub_id,
                expected_principal_id=args.principal_id, expected_access_label_ref=label_ref)
        except (ValidationFailure, OSError, RecursionError) as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{
                "code": getattr(exc, "code", "claim-storage-unavailable"),
                "message": getattr(exc, "message", "claim outcome is unverified; storage is unavailable"),
            }]}, args.as_json)
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK

    if args.command == "sync":
        try:
            is_http = "://" in args.hub
            if not is_http and (not args.session_id or not args.completed_at):
                raise SyncFailure("sync-local-binding-required", "local sync requires session-id and completed-at")
            try:
                http_label_ref = json.loads(args.access_label_ref) if args.access_label_ref else None
            except ValueError:
                raise SyncFailure("sync-http-binding-required", "access-label-ref must be a JSON record reference") from None
            link = None
            if args.repo is not None:
                if is_http:
                    raise SyncFailure("sync-http-repo-binding-unsupported", "HTTP repo onboarding is not yet supported")
                link = require_repo_onboarding(args.repo, args.vault)
            result = sync_coordination(
                args.vault,
                args.hub if is_http else Path(args.hub),
                session_id=args.session_id,
                completed_at=args.completed_at,
                phase=args.phase,
                required_project_id=(link["project_id"] if link else None),
                expected_hub_id=(link["hub_id"] if link else args.hub_id),
                expected_access_label_ref=(
                    link["access_label_ref"] if link else http_label_ref
                ),
                expected_principal_id=args.principal_id,
                bearer=os.environ.get(args.bearer_env) if is_http else None,
            )
        except (SyncFailure, ValidationFailure, OSError) as exc:
            _receipt(
                {
                    "outcome": "rejected",
                    "diagnostics": [
                        {
                            "code": getattr(exc, "code", "sync-storage-unavailable"),
                            "message": getattr(exc, "message", "sync storage is unavailable"),
                        }
                    ],
                },
                args.as_json,
            )
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK

    if args.command == "onboard":
        try:
            result = onboard_project(
                args.repo,
                args.vault,
                args.hub,
                session_id=args.session_id,
                completed_at=args.completed_at,
                project_id=args.project_id,
                human_name=args.human_name,
            )
        except (SyncFailure, ValidationFailure, OSError, RecursionError) as exc:
            _receipt(
                {
                    "outcome": "rejected",
                    "diagnostics": [
                        {
                            "code": getattr(exc, "code", "onboard-storage-unavailable"),
                            "message": getattr(
                                exc,
                                "message",
                                "coordination onboarding storage is unavailable",
                            ),
                        }
                    ],
                },
                args.as_json,
            )
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK

    if args.command == "kickoff":
        try:
            result = build_kickoff_pack(
                args.vault,
                args.project,
                repo_root=args.repo,
            )
            prompt = render_kickoff_prompt(result)
        except (SyncFailure, ValidationFailure, OSError, RecursionError) as exc:
            _receipt(
                {
                    "outcome": "rejected",
                    "diagnostics": [
                        {
                            "code": getattr(exc, "code", "kickoff-storage-unavailable"),
                            "message": getattr(
                                exc,
                                "message",
                                "coordination kickoff evidence is unavailable",
                            ),
                        }
                    ],
                },
                args.as_json,
            )
            return EXIT_INVALID
        if args.as_json:
            _receipt(result, True)
        else:
            print(prompt, end="")
        return EXIT_OK

    if args.command == "coordination-context":
        try:
            with open_coordination_context_pack(args.vault) as result:
                _receipt(result, args.as_json)
                sys.stdout.flush()
        except (SyncFailure, ValidationFailure, OSError, RecursionError) as exc:
            _receipt(
                {
                    "outcome": "rejected",
                    "diagnostics": [
                        {
                            "code": getattr(
                                exc,
                                "code",
                                "coordination-context-storage-unavailable",
                            ),
                            "message": getattr(
                                exc,
                                "message",
                                "authorized coordination context is unavailable",
                            ),
                        }
                    ],
                },
                args.as_json,
            )
            return EXIT_INVALID
        return EXIT_OK

    if args.command == "import-session-ledger":
        try:
            result = import_session_ledger(
                args.done_log,
                args.vault,
                dry_run=args.dry_run,
            )
        except (SyncFailure, ValidationFailure, OSError, RecursionError) as exc:
            _receipt(
                {
                    "outcome": "rejected",
                    "diagnostics": [
                        {
                            "code": getattr(
                                exc,
                                "code",
                                "session-ledger-storage-unavailable",
                            ),
                            "message": getattr(
                                exc,
                                "message",
                                "session-ledger import storage is unavailable",
                            ),
                        }
                    ],
                },
                args.as_json,
            )
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK

    if args.command == "version":
        _receipt({"implementation": "artifact-memory-python", "version": __version__, "contract_version": CONTRACT_VERSION}, args.as_json)
        return EXIT_OK
    if args.command == "verify-release-candidate":
        try:
            result = verify_checked_out_release_candidate(
                args.manifest,
                args.tag,
                args.repo,
                asset_directory=args.asset_dir,
                owner_fingerprint=args.owner_fingerprint,
                isolated_checkout=args.isolated_checkout,
            )
        except ValidationFailure as exc:
            _receipt(
                {"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]},
                args.as_json,
            )
            return EXIT_INVALID
        if args.as_json:
            _receipt(result, True)
        else:
            print(render_release_candidate_verification_receipt(result), end="")
        return EXIT_OK
    if args.command == "validate-release-candidate-preparation-receipt":
        try:
            receipt = load_json(args.receipt)
            if not isinstance(receipt, dict):
                raise ValidationFailure(
                    "invalid-input",
                    "release candidate preparation receipt must be an object",
                )
            validate_release_candidate_preparation_receipt(receipt)
        except ValidationFailure as exc:
            _receipt(
                {"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]},
                args.as_json,
            )
            return EXIT_INVALID
        if args.as_json:
            _receipt(
                {
                    "outcome": "integrity-verified",
                    "receipt_id": receipt["receipt_id"],
                    "tag_message_trailer": receipt["tag_message_trailer"],
                    "verification_scope": "receipt-schema-canonical-identity-and-trailer-coherence-only",
                    "owner_signature_verified": False,
                },
                True,
            )
        else:
            print(render_release_candidate_preparation_receipt(receipt), end="")
        return EXIT_OK
    if args.command == "validate-release-candidate-receipt":
        try:
            receipt = load_json(args.receipt)
            if not isinstance(receipt, dict):
                raise ValidationFailure("invalid-input", "release verification receipt must be an object")
            validate_release_candidate_verification_receipt(receipt)
        except ValidationFailure as exc:
            _receipt(
                {"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]},
                args.as_json,
            )
            return EXIT_INVALID
        _receipt(
            {
                "outcome": "integrity-verified",
                "receipt_id": receipt["receipt_id"],
                "verification_scope": "receipt-schema-canonical-identity-and-internal-coherence-only",
                "live_release_evidence_verified": False,
            },
            args.as_json,
        )
        return EXIT_OK
    if args.command == "scan":
        manifest, receipt = scan_path(args.root)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            (args.out / "scan-receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        _receipt({"outcome": receipt["outcome"], "manifest_ref": manifest["manifest_id"], "tree_digest": manifest["tree_digest"], "accounted_entry_count": receipt["accounted_entry_count"], "diagnostic_count": len(receipt["diagnostics"])}, args.as_json)
        return EXIT_OK if receipt["outcome"] == "complete" else EXIT_INVALID
    if args.command == "verify":
        try:
            manifest = load_json(args.manifest)
            policy = load_json(args.policy) if args.policy else None
            if not isinstance(manifest, dict) or (policy is not None and not isinstance(policy, dict)):
                raise ValidationFailure("invalid-input", "manifest and policy must be JSON objects")
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        result = verify_path(args.root, manifest, policy=policy)
        _receipt(result, args.as_json)
        if result["outcome"] == "verified":
            return EXIT_OK
        return EXIT_UNSUPPORTED if result["outcome"] in {"policy-required", "unsupported"} else EXIT_INVALID
    if args.command == "diff":
        try:
            before = load_json(args.before)
            after = load_json(args.after)
            if not isinstance(before, dict) or not isinstance(after, dict):
                raise ValidationFailure("invalid-input", "manifests must be JSON objects")
            result = diff_manifests(before, after)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK if result["outcome"] == "complete" else EXIT_INVALID
    if args.command == "project":
        try:
            result = project_records(args.records, args.out)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK
    if args.command == "search":
        try:
            record_ids = search_records(args.index, args.query, literal=args.literal, exclude_superseded=args.exclude_superseded, rank=args.rank)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt({"outcome": "complete", "record_ids": record_ids}, args.as_json)
        return EXIT_OK
    if args.command == "search-receipt":
        try:
            receipt = search_receipt(args.index, args.query, literal=args.literal, exclude_superseded=args.exclude_superseded, rank=args.rank)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt(receipt, args.as_json)
        return EXIT_OK
    if args.command == "related":
        try:
            relationships = related_records(args.index, args.record_id)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt({"outcome": "complete", "record_id": args.record_id, "relationships": relationships}, args.as_json)
        return EXIT_OK
    if args.command == "provenance":
        try:
            records = records_with_provenance(args.index, args.source_ref)
        except ValidationFailure as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": exc.code, "message": exc.message}]}, args.as_json)
            return EXIT_INVALID
        _receipt({"outcome": "complete", "source_ref": args.source_ref, "records": records}, args.as_json)
        return EXIT_OK
    if args.command == "context":
        try:
            records = [load_json(path) for path in args.records]
            evidence = load_json(args.evidence) if args.evidence else []
            record_ids = [record.get("record_id") for record in records if isinstance(record, dict)]
            result = export_context(
                records,
                evidence,
                args.allow_sensitivity,
                args.max_bytes,
                supported_required_extensions=[tuple(item) for item in args.supported_required_extensions],
                supported_context_schema_ids=(
                    args.supported_context_schema_ids
                    or ["artifact-memory/context-pack/v2", "artifact-memory/context-pack/v3"]
                ),
                **build_selection_policy(
                    record_ids,
                    selected_at=args.selected_at,
                    freshness_basis=args.freshness_basis,
                    authorized_evidence=[tuple(item) for item in args.authorized_evidence],
                ),
            )
        except (ValidationFailure, ContextFailure) as exc:
            _receipt({"outcome": "rejected", "diagnostics": [{"code": getattr(exc, "code", "invalid-input"), "message": getattr(exc, "message", str(exc))}]}, args.as_json)
            return EXIT_INVALID
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "context-pack.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        exclusions = result["selection_receipt"]["exclusion_counts"]
        _receipt({"outcome": "complete", "pack_id": result["pack_id"], "selected_record_count": len(result["records"]), "excluded_record_count": sum(exclusions.values()), "authority_boundary": result["authority_boundary"]}, args.as_json)
        return EXIT_OK
    if args.command == "import-codex-history":
        try:
            task = load_json(args.task_export)
            policy = load_json(args.policy)
            if not isinstance(task, dict) or not isinstance(policy, dict):
                raise ValidationFailure("invalid-input", "task export and policy must be objects")
            result = import_task_export(task, policy)
            if result["declassification_receipt"]["outcome"] != "admitted":
                _receipt(
                    {
                        "outcome": "not-authorized",
                        "records_written": 0,
                        "owner_review_required": True,
                    },
                    args.as_json,
                )
                return EXIT_INVALID
            write_import_bundle(result, args.out)
        except (ValidationFailure, OSError, ValueError) as exc:
            _receipt(
                {
                    "outcome": "rejected",
                    "records_written": 0,
                    "diagnostics": [
                        {
                            "code": getattr(exc, "code", "output-unavailable"),
                            "message": getattr(exc, "message", "local import output is unavailable"),
                        }
                    ],
                },
                args.as_json,
            )
            return EXIT_INVALID
        counts = result["declassification_receipt"]["record_type_counts"]
        _receipt(
            {
                "outcome": "complete",
                "records_written": len(result["records"]),
                "record_type_counts": counts,
                "owner_review_required": True,
                "authority_boundary": result["declassification_receipt"]["authority_boundary"],
            },
            args.as_json,
        )
        return EXIT_OK
    if args.command == "codex-history-dogfood-receipt":
        try:
            private_receipt = load_json(args.private_declassification_receipt)
            if not isinstance(private_receipt, dict):
                raise ValidationFailure(
                    "invalid-input", "private declassification receipt must be an object"
                )
            result = sanitize_private_import_receipt(
                private_receipt,
                performed_at=args.performed_at,
            )
        except ValidationFailure as exc:
            _receipt(
                {
                    "outcome": "rejected",
                    "diagnostics": [{"code": exc.code, "message": exc.message}],
                },
                args.as_json,
            )
            return EXIT_INVALID
        _receipt(result, args.as_json)
        return EXIT_OK
    try:
        record = load_json(args.record)
    except ValidationFailure as exc:
        _receipt({"valid": False, "outcome": "rejected", "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}]}, args.as_json)
        return EXIT_INVALID
    if not isinstance(record, dict):
        _receipt({"valid": False, "outcome": "rejected", "diagnostics": [{"code": "invalid-input", "path": "$", "message": "record must be a JSON object"}]}, args.as_json)
        return EXIT_INVALID
    schema_id = record.get("schema_id")
    try:
        schema = load_json(args.schema) if args.schema else _schemas().get(schema_id)
    except ValidationFailure as exc:
        _receipt({"valid": False, "outcome": "rejected", "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}]}, args.as_json)
        return EXIT_INVALID
    if schema is None:
        _receipt({"valid": False, "outcome": "unsupported", "schema_id": schema_id, "diagnostics": [{"code": "schema-unsupported", "path": "$.schema_id", "message": "no supported v0 schema"}]}, args.as_json)
        return EXIT_UNSUPPORTED
    if args.command == "inspect":
        _receipt({"outcome": "inspected", "schema_id": schema_id, "field_names": sorted(record)}, args.as_json)
        return EXIT_OK
    try:
        if not isinstance(schema, dict):
            raise ValidationFailure("invalid-input", "schema must be a JSON object")
        validate(record, schema)
        if schema_id in {
            "artifact-memory/release-manifest/v1",
            "artifact-memory/release-manifest/v2",
            "artifact-memory/release-manifest/v3",
        }:
            validate_release_manifest(record)
        if schema_id in {
            "artifact-memory/release-preparation-receipt/v1",
            "artifact-memory/release-preparation-receipt/v2",
        }:
            validate_release_preparation_receipt(record)
        if schema_id in {
            "artifact-memory/archive-receipt/v1",
            "artifact-memory/archive-receipt/v2",
        }:
            validate_archive_receipt(record)
        if schema_id in CONTEXT_READ_SCHEMAS:
            try:
                validate_context_pack(record)
            except ContextFailure as exc:
                raise ValidationFailure(exc.code, exc.message) from exc
        if schema_id == SYNC_RECEIPT_SCHEMA_ID:
            validate_sync_receipt(record)
        if schema_id == BOOTSTRAP_PACK_SCHEMA_ID:
            validate_bootstrap_pack(record)
        if schema_id == BOOTSTRAP_RECEIPT_SCHEMA_ID:
            validate_bootstrap_receipt(record)
        if schema_id in KICKOFF_PACK_SCHEMA_IDS:
            validate_kickoff_pack(record)
        if schema_id == COORDINATION_CONTEXT_PACK_SCHEMA_ID:
            validate_coordination_context_pack(record)
            raise ValidationFailure(
                "coordination-context-policy-evidence-required",
                (
                    "detached validation cannot verify the referenced sync receipt; "
                    "export from a verified vault with coordination-context"
                ),
                "$.sync_observation.receipt_id",
            )
    except ValidationFailure as exc:
        result = {"valid": False, "outcome": "rejected", "diagnostics": [{"code": exc.code, "path": exc.path, "message": exc.message}]}
    else:
        result = {"valid": True, "outcome": "accepted", "diagnostics": []}
    result["schema_id"] = schema_id
    _receipt(result, args.as_json)
    return EXIT_OK if result["valid"] else EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
