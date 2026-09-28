"""Synthetic transport attacks; real WITS pickup proof is separately opt-in."""
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

from artifact_memory.canonical import canonical_bytes
from artifact_memory.coordination import revision_digest
from artifact_memory.coordination_claim import claim_http
from artifact_memory.coordination_sync import SyncFailure, build_pull_response, store_coordination_record
from tests.test_coordination_sync import (
    HUB_ID, PRINCIPAL, PROJECT_A, PROJECT_B, SESSION, claimed_task_for, configure, label_for,
)


class HttpClaimTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.hub, self.vault = self.root / 'hub', self.root / 'worker'
        self.label = label_for([PROJECT_A])
        configure(self.hub, self.label)
        self.opened, self.claimed = claimed_task_for(self.label)
        self.open_ref = store_coordination_record(self.hub, self.opened)
        self.claimed_ref = {'record_id': self.claimed['record_id'], 'revision_digest': revision_digest(self.claimed)}
        self.claims = []
        self.syncs = 0
        self.deny = None
        self.response_override = None
        self.drop = False
        self.hide_successor = False
        self.fail_pull = False
        self.admitted = False
        self.redirect = False
        self.before = build_pull_response(self.hub, session_id=SESSION, completed_at='2026-09-27T23:00:00Z')
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                raw = canonical_bytes(body)
                self.send_response(status)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path == '/api/agent/coordination/sync':
                    outer.syncs += 1
                    if outer.fail_pull and outer.admitted:
                        self.reply(503, {'secret': 'synthetic-bearer'})
                        return
                    response = outer.before if outer.hide_successor else build_pull_response(
                        outer.hub, session_id=SESSION, completed_at=f'2026-09-27T23:00:{outer.syncs:02d}Z')
                    self.reply(200, response)
                    return
                outer.claims.append((self.path, body, self.headers.get('Authorization')))
                if outer.redirect:
                    self.send_response(302)
                    self.send_header('Location', outer.url + '/credential-sink')
                    self.end_headers()
                    return
                if outer.deny:
                    self.reply(outer.deny, {'secret': 'synthetic-bearer'})
                    return
                replay = outer.admitted
                store_coordination_record(outer.hub, outer.claimed)
                outer.admitted = True
                if outer.drop:
                    self.close_connection = True
                    return
                self.reply(200 if replay else 201, outer.response_override or {
                    'taskRef': outer.claimed_ref, 'replay': replay,
                })

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.binding = dict(task_ref=self.open_ref, project_id=PROJECT_A, bearer='synthetic-bearer',
            expected_hub_id=HUB_ID, expected_principal_id=PRINCIPAL,
            expected_access_label_ref={'record_id': self.label['record_id'], 'revision_digest': revision_digest(self.label)})

    def pickup(self, **overrides):
        return claim_http(self.vault, self.url, **(self.binding | overrides))

    def test_new_claim_and_exact_replay_require_verified_successor(self):
        first = self.pickup()
        self.assertEqual(first['outcome'], 'verified')
        self.assertFalse(first['replay'])
        self.assertEqual(first['task_ref'], self.claimed_ref)
        self.assertEqual(first['requested_task_ref'], self.open_ref)
        self.assertEqual(first['claim_id'], self.claimed['claims'][0]['claimId'])
        self.assertEqual(self.syncs, 2)
        self.assertTrue(self.pickup()['replay'])
        self.assertTrue(all(path == '/api/agent/coordination/claims' and body == {'taskRef': self.open_ref}
                            and auth == 'Bearer synthetic-bearer' for path, body, auth in self.claims))
        self.assertNotIn(b'synthetic-bearer', canonical_bytes(first))
        self.assertTrue(all(b'synthetic-bearer' not in file.read_bytes() for file in self.vault.rglob('*.json')))

    def test_conflict_denial_and_redirect_never_choose_another_task_or_retry(self):
        for status, code in [(401, 'claim-unauthenticated'), (403, 'claim-unauthorized'), (409, 'claim-conflict')]:
            with self.subTest(status=status):
                self.deny = status
                before = len(self.claims)
                with self.assertRaises(SyncFailure) as caught:
                    self.pickup()
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('synthetic-bearer', str(caught.exception))
                self.assertEqual(len(self.claims), before + 1)
                self.assertFalse(self.admitted)
        self.deny = None
        self.redirect = True
        with self.assertRaises(SyncFailure):
            self.pickup()
        self.assertNotIn('/credential-sink', [path for path, _, _ in self.claims])

    def test_missing_credential_bad_ref_and_insecure_hub_stop_before_network(self):
        for changes in [dict(bearer=None), dict(task_ref={'record_id': 'wrong'}), dict(project_id='wrong')]:
            with self.subTest(changes=changes), self.assertRaises(SyncFailure):
                self.pickup(**changes)
        with self.assertRaises(SyncFailure):
            claim_http(self.vault, 'http://synthetic-hub.invalid', **self.binding)
        self.assertEqual(self.syncs, 0)
        self.assertEqual(self.claims, [])

    def test_wrong_project_principal_label_and_stale_ref_never_claim(self):
        cases = [dict(project_id=PROJECT_B), dict(expected_principal_id='coordination-principal://synthetic/other'),
                 dict(expected_access_label_ref=self.binding['expected_access_label_ref'] | {'revision_digest': 'sha-256:' + '0' * 64}),
                 dict(task_ref=self.open_ref | {'revision_digest': 'sha-256:' + '0' * 64}), dict(task_ref=self.claimed_ref)]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(SyncFailure):
                self.pickup(**changes)
        self.assertEqual(self.claims, [])

    def test_lost_claim_response_is_unverified_until_explicit_exact_replay(self):
        self.drop = True
        with self.assertRaises(SyncFailure) as caught:
            self.pickup()
        self.assertEqual(caught.exception.code, 'claim-http-unavailable')
        self.assertTrue(self.admitted)
        self.assertEqual(len(self.claims), 1)
        self.drop = False
        result = self.pickup()
        self.assertTrue(result['replay'])
        self.assertEqual(result['requested_task_ref'], self.open_ref)
        self.assertEqual(len(self.claims), 2)

    def test_success_response_without_authorized_successor_is_not_pickup(self):
        self.hide_successor = True
        with self.assertRaises(SyncFailure) as caught:
            self.pickup()
        self.assertEqual(caught.exception.code, 'claim-result-unverified')
        self.assertEqual(len(self.claims), 1)

    def test_failed_post_claim_pull_never_reports_success(self):
        self.fail_pull = True
        with self.assertRaises(SyncFailure) as caught:
            self.pickup()
        self.assertEqual(caught.exception.code, 'claim-result-unverified')
        self.assertTrue(self.admitted)
        self.assertEqual(len(self.claims), 1)

    def test_strict_response_shape_replay_and_exact_identity(self):
        responses = [dict(taskRef=self.claimed_ref, replay=True), dict(taskRef=self.claimed_ref, replay=0),
                     dict(taskRef=self.claimed_ref, replay=False, extra=True), dict(taskRef={'record_id': 'bad'}, replay=False),
                     dict(taskRef=self.claimed_ref | {'record_id': self.claimed_ref['record_id'][:-1] + '3'}, replay=False)]
        for response in responses:
            with self.subTest(response=response):
                self.response_override = response
                self.admitted = False
                with self.assertRaises(SyncFailure):
                    self.pickup()
        self.assertEqual(len(self.claims), len(responses))

    def test_cli_reads_credential_from_environment_and_returns_ref_only_receipt(self):
        args = [sys.executable, '-m', 'artifact_memory', 'claim', '--vault', str(self.vault), '--hub', self.url,
                '--hub-id', HUB_ID, '--project-id', PROJECT_A, '--principal-id', PRINCIPAL,
                '--task-ref', json.dumps(self.open_ref), '--access-label-ref', json.dumps(self.binding['expected_access_label_ref']),
                '--bearer-env', 'SYNTHETIC_CLAIM_KEY', '--json']
        result = subprocess.run(args, capture_output=True, text=True, env=os.environ | {'SYNTHETIC_CLAIM_KEY': 'synthetic-bearer'})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['outcome'], 'verified')
        self.assertNotIn('synthetic-bearer', result.stdout + result.stderr)
        self.assertNotIn('dod', receipt)
        self.assertNotIn('scopeFence', receipt)
        self.assertIn('authority_boundary', receipt)
