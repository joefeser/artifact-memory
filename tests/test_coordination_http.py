"""Transport adversarial fixtures; actual WITS proof is the opt-in integration."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from artifact_memory.coordination_sync import (
    SyncFailure, build_pull_response, directory_digest, store_coordination_record, sync,
)
from artifact_memory.coordination import revision_digest
from artifact_memory.canonical import canonical_bytes
from artifact_memory.validator import ValidationFailure
from tests.test_coordination_sync import (
    HUB_ID, PRINCIPAL, SESSION, configure, label_for, unique_task_for, PROJECT_A,
)


class HttpCoordinationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault, self.hub = self.root / "vault", self.root / "hub"
        self.label = label_for([PROJECT_A])
        configure(self.hub, self.label)
        self.tasks = [unique_task_for(self.label, i) for i in range(3)]
        for task in self.tasks:
            store_coordination_record(self.hub, task)
        self.vault.mkdir()
        self.requests = []
        self.failure_page = None
        self.redirect = False
        self.paused = None
        self.responses = []
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((payload, self.headers.get("Authorization")))
                if outer.paused:
                    outer.paused[0].set()
                    outer.paused[1].wait(timeout=10)
                if outer.redirect:
                    self.send_response(302)
                    self.send_header('Location', outer.url + '/credential-sink')
                    self.end_headers()
                    return
                index = 0 if payload["page_token"] is None else int(payload["page_token"].split("-")[-1])
                if index == outer.failure_page:
                    self.send_response(401)
                    self.end_headers()
                    return
                raw = canonical_bytes(outer.responses[index])
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.label_ref = {"record_id": self.label["record_id"], "revision_digest": revision_digest(self.label)}
        self.binding = dict(session_id=SESSION, completed_at="ignored", bearer="synthetic-bearer",
            expected_hub_id=HUB_ID, expected_principal_id=PRINCIPAL, expected_access_label_ref=self.label_ref)
        self.response()

    def response(self, outcomes=None):
        with patch("artifact_memory.coordination_sync.MAX_PAGE_RECORDS", 2):
            result = build_pull_response(self.hub, session_id=SESSION,
                completed_at="2026-09-27T23:00:00Z", submission_outcomes=outcomes)
        self.responses = []
        for index, (page, records) in enumerate(zip(result["pages"], result["record_pages"])):
            page["next_token"] = None if index + 1 == len(result["pages"]) else f"opaque-{index + 1}"
            self.responses.append({"receipt": result["receipt"], "pages": [page], "record_pages": [records]})

    def test_opaque_pages_verify_before_projection_and_noop(self):
        result = sync(self.vault, self.url, phase="pull", **self.binding)
        self.assertEqual(result["receipt"]["authorized_membership"]["pair_count"], 3)
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(auth == "Bearer synthetic-bearer" for _, auth in self.requests))
        before = directory_digest(self.vault)
        self.assertEqual(sync(self.vault, self.url, phase="pull", **self.binding)["outcome"], "no-op")
        self.assertEqual(directory_digest(self.vault), before)
        files = list((self.vault / "generated").rglob("*.json"))
        self.assertTrue(all(b"opaque-" not in p.read_bytes() and b"synthetic-bearer" not in p.read_bytes() for p in files))

    def test_missing_page_retains_exact_retry_batch_without_success(self):
        task = self.tasks[0]
        ref = store_coordination_record(self.vault, task)
        outcomes = [{"record_ref": ref, "outcome": "admitted", "code": "admitted"}]
        self.response(outcomes)
        self.failure_page = 1
        with self.assertRaises(SyncFailure) as caught:
            sync(self.vault, self.url, **self.binding)
        self.assertEqual(caught.exception.code, "sync-http-rejected")
        self.assertFalse((self.vault / "generated/coordination-sync/last-successful.json").exists())
        pending = self.vault / "generated/coordination-sync/http-pending.json"
        self.assertTrue(pending.exists())
        self.assertNotIn(b"synthetic-bearer", pending.read_bytes())
        # Local appends during interruption cannot replace the outstanding batch.
        store_coordination_record(self.vault, self.tasks[1])
        self.failure_page = None
        result = sync(self.vault, self.url, phase="pull", **self.binding)
        self.assertEqual(result["submission_outcomes"], outcomes)
        self.assertEqual(self.requests[-2][0]["records"][0]["record_ref"], ref)
        self.assertEqual(len(self.requests[-2][0]["records"]), 1)
        self.assertFalse(pending.exists())

    def test_forged_records_or_page_receipt_never_advance_marker(self):
        for mutation in ("record", "receipt", "index", "token", "binding"):
            with self.subTest(mutation=mutation):
                self.response()
                if mutation == "record":
                    self.responses[1]["record_pages"][0][0]["title"] = "tampered"
                elif mutation == "receipt":
                    self.responses[1]["receipt"] = copy.deepcopy(self.responses[1]["receipt"])
                    self.responses[1]["receipt"]["excluded_count"] += 1
                elif mutation == "index":
                    self.responses[1]["pages"][0]["page_index"] = 0
                elif mutation == "token":
                    self.responses[0]["pages"][0]["next_token"] = None
                else:
                    self.binding["expected_principal_id"] = "coordination-principal://synthetic/other"
                with self.assertRaises(ValidationFailure):
                    sync(self.vault, self.url, phase="pull", **self.binding)
                self.assertFalse((self.vault / "generated/coordination-sync/last-successful.json").exists())

    def test_requires_pinned_binding_and_secure_endpoint_before_network(self):
        for url, changes in (("http://example.invalid", {}),
                             (self.url + "/other", {}),
                             (self.url, {"bearer": None}),
                             (self.url, {"expected_principal_id": None}),
                             ("https://user:secret@example.invalid", {})):
            with self.subTest(url=url), self.assertRaises(SyncFailure):
                sync(self.vault, url, phase="pull", **(self.binding | changes))
        self.assertEqual(self.requests, [])

    def test_cli_accepts_url_and_env_bearer_without_local_session_time(self):
        command = [sys.executable, '-m', 'artifact_memory', 'sync', '--vault', str(self.vault),
            '--hub', self.url, '--hub-id', HUB_ID, '--principal-id', PRINCIPAL,
            '--access-label-ref', json.dumps(self.label_ref), '--phase', 'pull', '--json']
        result = subprocess.run(command, env=os.environ | {'ARTIFACT_MEMORY_COORDINATION_BEARER': 'synthetic-bearer'},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['receipt']['authorized_membership']['pair_count'], 3)
        self.assertNotIn('synthetic-bearer', result.stdout + result.stderr)

    def test_redirect_is_rejected_without_forwarding_bearer(self):
        self.redirect = True
        with self.assertRaises(SyncFailure) as caught:
            sync(self.vault, self.url, phase='pull', **self.binding)
        self.assertEqual(caught.exception.code, 'sync-http-rejected')
        self.assertEqual(len(self.requests), 1)
        self.assertFalse((self.vault / 'generated/coordination-sync/last-successful.json').exists())

    def test_two_principals_cannot_race_one_local_retry_journal(self):
        entered, release = threading.Event(), threading.Event()
        self.paused = (entered, release)
        returned = []
        def first():
            returned.append(sync(self.vault, self.url, phase='pull', **self.binding))
        worker = threading.Thread(target=first)
        worker.start()
        try:
            self.assertTrue(entered.wait(timeout=5))
            with self.assertRaises(SyncFailure) as caught:
                sync(self.vault, self.url, phase='pull', **(self.binding | {
                    'expected_principal_id': 'coordination-principal://synthetic/other'}))
            self.assertEqual(caught.exception.code, 'sync-principal-busy')
        finally:
            release.set()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(returned), 1)

    def test_oversized_response_and_unrelated_outcomes_cannot_apply(self):
        with patch('artifact_memory.coordination_http.MAX_PAGE_BYTES', 100):
            with self.assertRaises(SyncFailure) as caught:
                sync(self.vault, self.url, phase='pull', **self.binding)
        self.assertEqual(caught.exception.code, 'sync-page-too-large')
        self.response([{'record_ref': {'record_id': self.tasks[0]['record_id'],
            'revision_digest': revision_digest(self.tasks[0])}, 'outcome': 'admitted', 'code': 'admitted'}])
        with self.assertRaises(SyncFailure) as caught:
            sync(self.vault, self.url, phase='pull', **self.binding)
        self.assertEqual(caught.exception.code, 'sync-outcomes-invalid')
        self.assertFalse((self.vault / 'generated/coordination-sync/last-successful.json').exists())


if __name__ == "__main__":
    unittest.main()
