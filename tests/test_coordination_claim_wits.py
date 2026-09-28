"""Opt-in publisher/worker/observer pickup against real pinned WITS routes."""
import json
import ipaddress
import sys
import os
import select
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from artifact_memory.canonical import canonical_bytes
from artifact_memory.coordination import revision_digest
from artifact_memory.coordination_claim import claim_http
from artifact_memory.coordination_sync import load_authorized_projection, store_coordination_record, sync
from tests.test_coordination_sync import (
    HUB_ID, PRINCIPAL, PROJECT_A, PROJECT_B, SESSION, configure, label_for, unique_task_for, work_receipt_for,
)

# Filled from the reviewed claim-policy repair, independently of the original AM-153 pin.
WITS_CLAIM_REF = '5a04c0d7d6d834f1708eda85b286ef576fa8d0af'


@unittest.skipUnless(os.environ.get('RUN_WITS_CLAIM_INTEGRATION') == '1', 'opt-in WITS task pickup integration')
class WitsClaimIntegration(unittest.TestCase):
    def test_publisher_worker_observer_and_explicit_replay(self):
        wits = Path(os.environ['WITS_SOURCE_ROOT'])
        self.assertEqual(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=wits, text=True).strip(), WITS_CLAIM_REF)
        subprocess.run(['git', 'diff', '--exit-code', 'HEAD', '--', 'app', 'lib', 'prisma'], cwd=wits, check=True, capture_output=True)
        self.assertEqual(os.environ.get('AM156_DISPOSABLE_DATABASE'), 'synthetic')
        database = urlsplit(os.environ['TEST_DATABASE_URL'])
        self.assertEqual(database.username, 'synthetic')
        self.assertEqual(database.password, 'synthetic')
        self.assertEqual(database.path, '/synthetic')
        self.assertTrue(database.hostname == 'localhost' or ipaddress.ip_address(database.hostname).is_loopback)
        with tempfile.TemporaryDirectory(prefix='am156-synthetic-') as temporary:
            root = Path(temporary)
            hub, publisher, worker, observer = (root / name for name in ('hub', 'publisher', 'worker', 'observer'))
            label = label_for([PROJECT_A])
            configure(hub, label)
            label_ref = {'record_id': label['record_id'], 'revision_digest': revision_digest(label)}
            opened = unique_task_for(label, 700)
            opened['assignedWriter'] = PRINCIPAL
            open_ref = store_coordination_record(publisher, opened)
            hidden = unique_task_for(label, 800)
            hidden.update(originId='44444444-4444-4444-8444-444444444444', projectId=PROJECT_B, projectName='sample-analytics')
            hidden['record_id'] = f"record://coordination/{hidden['originId']}/task/{hidden['taskId']}"
            store_coordination_record(hub, hidden)
            (hub / 'policy/coordination-origin-projects.json').write_bytes(canonical_bytes({
                'schema_id': 'wits/coordination-origin-projects/v0',
                'origins': {opened['originId']: PROJECT_A, hidden['originId']: PROJECT_B},
            }))
            publisher_principal = 'coordination-principal://synthetic/publisher'
            observer_principal = 'coordination-principal://synthetic/observer'
            other_principal = 'coordination-principal://synthetic/other-worker'
            config = json.loads((hub / 'hub-config.json').read_bytes())
            for principal in [publisher_principal, observer_principal, other_principal]:
                config['bindings'].append({'session_id': 'coordination-session://synthetic/' + principal.rsplit('/', 1)[-1],
                    'principal_id': principal, 'access_label': label})
            (hub / 'hub-config.json').write_bytes(canonical_bytes(config))
            publisher_token, worker_token, observer_token, other_token = (
                'synthetic-am156-publisher', 'synthetic-am156-worker', 'synthetic-am156-observer', 'synthetic-am156-other')
            seed = root / 'synthetic-seed.json'
            keys = []
            for token, principal, actions in [
                (publisher_token, publisher_principal, ['read', 'sync:task-packet']),
                (worker_token, PRINCIPAL, ['read', 'claim', 'sync:work-receipt']),
                (observer_token, observer_principal, ['read']),
                (other_token, other_principal, ['read', 'claim']),
            ]:
                keys.append({'projectId': PROJECT_A, 'token': token, 'principal': principal, 'labelRef': label_ref,
                    'capabilities': [f'coordination:{action}:{PROJECT_A}' for action in actions]})
            seed.write_bytes(canonical_bytes({'projects': [
                {'id': PROJECT_A, 'name': 'sample-service'}, {'id': PROJECT_B, 'name': 'sample-analytics'}], 'keys': keys}))
            env = os.environ | {'DATABASE_URL': os.environ['TEST_DATABASE_URL'], 'WITS_HTTP_SYNTHETIC_SEED': str(seed),
                'COORDINATION_VAULT_ROOT': str(hub), 'BUS_TRANSPORT': 'in_process',
                'COORDINATION_SYNC_TOKEN_SECRET': 'synthetic-am156-server-secret-not-a-production-key'}
            script = Path(__file__).parent / 'integration/wits-http-hub.mts'
            with (root / 'server.stderr').open('w') as stderr:
                server = subprocess.Popen(['node', '--import', 'tsx', str(script.resolve())], cwd=wits,
                    env=env, stdout=subprocess.PIPE, stderr=stderr, text=True)
                try:
                    self.assertTrue(select.select([server.stdout], [], [], 30)[0], 'synthetic WITS server did not start')
                    ready = server.stdout.readline()
                    self.assertTrue(ready, 'synthetic WITS server exited before readiness')
                    url = f"http://127.0.0.1:{json.loads(ready)['port']}"
                    def binding(token, principal):
                        return dict(bearer=token, expected_hub_id=HUB_ID,
                            expected_principal_id=principal, expected_access_label_ref=label_ref)
                    published = sync(publisher, url, **binding(publisher_token, publisher_principal))
                    self.assertEqual([item['code'] for item in published['submission_outcomes']], ['admitted'])
                    args = [sys.executable, '-m', 'artifact_memory', 'claim',
                        '--vault', str(worker), '--hub', url, '--hub-id', HUB_ID, '--project-id', PROJECT_A,
                        '--principal-id', PRINCIPAL, '--access-label-ref', json.dumps(label_ref),
                        '--task-ref', json.dumps(open_ref), '--bearer-env', 'SYNTHETIC_WORKER_KEY', '--json']
                    picked = subprocess.run(args, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                        env=os.environ | {'SYNTHETIC_WORKER_KEY': worker_token}, timeout=60)
                    self.assertEqual(picked.returncode, 0, picked.stdout + picked.stderr)
                    pickup = json.loads(picked.stdout)
                    self.assertEqual(pickup['outcome'], 'verified')
                    self.assertFalse(pickup['replay'])
                    claimed = next(r for r in load_authorized_projection(worker) if r.get('status') == 'claimed')
                    self.assertEqual(claimed['predecessor'], open_ref)
                    self.assertEqual(claimed['claims'][0]['principalId'], PRINCIPAL)
                    self.assertEqual(pickup['task_ref']['revision_digest'], revision_digest(claimed))
                    self.assertNotIn(worker_token, picked.stdout + picked.stderr)
                    replay = claim_http(worker, url, task_ref=open_ref, project_id=PROJECT_A, **binding(worker_token, PRINCIPAL))
                    self.assertTrue(replay['replay'])
                    self.assertEqual(replay['task_ref'], pickup['task_ref'])
                    request = Request(url + '/api/agent/coordination/claims', method='POST',
                        data=canonical_bytes({'taskRef': open_ref}), headers={'Authorization': 'Bearer ' + other_token})
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(request, timeout=20)
                    self.assertEqual(denied.exception.code, 409)
                    denied.exception.close()
                    # Harness-owned synthetic evidence, not execution of TaskPacket text.
                    check = subprocess.run([sys.executable, '-c', 'assert 1 + 1 == 2'], capture_output=True)
                    self.assertEqual(check.returncode, 0)
                    receipt = work_receipt_for(label, claimed)
                    receipt['evidence'] = [{'command': "python3 -c 'assert 1 + 1 == 2'", 'exitCode': check.returncode,
                        'counts': {'passed': 1, 'failed': 0, 'skipped': 0}, 'artifacts': []}]
                    receipt_ref = store_coordination_record(worker, receipt)
                    posted = sync(worker, url, **binding(worker_token, PRINCIPAL))
                    self.assertEqual(posted['submission_outcomes'], [{'record_ref': receipt_ref, 'outcome': 'admitted', 'code': 'admitted'}])
                    observed = sync(observer, url, phase='pull', **binding(observer_token, observer_principal))
                    self.assertEqual(observed['receipt']['excluded_count'], 1)
                    records = load_authorized_projection(observer)
                    self.assertEqual(len(records), 3)
                    self.assertEqual(next(r for r in records if r['schema_id'].endswith('work-receipt/v0')), receipt)
                    self.assertNotIn(hidden['record_id'].encode(), canonical_bytes(records))
                    self.assertTrue(all(b'synthetic-am156-' not in f.read_bytes() for f in worker.rglob('*.json')))
                finally:
                    server.terminate()
                    try: server.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        server.kill(); server.wait(timeout=10)
                    if server.stdout: server.stdout.close()
        print('AM156-WITS: published=1 claimed=1 replay=verified conflict=409 receipt=1 observed=3 excluded=1 execution=not-authorized')
