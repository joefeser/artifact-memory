"""Opt-in cross-repository proof against WITS's merged POST route.

Needs a disposable, schema-provisioned PostgreSQL DB and the pinned WITS tree.
No bearer, actual URL or machine-local path is included in the proof receipt.
"""
import copy
import json
import ipaddress
import os
import select
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from artifact_memory.canonical import canonical_bytes
from artifact_memory.coordination import revision_digest
from artifact_memory.coordination_sync import (
    _policy_label_path, _record_path, _write_immutable, directory_digest, load_authorized_projection,
    store_coordination_record, sync,
)
from tests.test_coordination_sync import (
    HUB_ID, PRINCIPAL, SESSION, PROJECT_A, PROJECT_B, configure, label_for, unique_task_for,
    claimed_task_for, work_receipt_for, label_identity,
)

WITS_REF = 'd07f850d07a447e7672ae40a0e61b67029e71d02'


@unittest.skipUnless(os.environ.get('RUN_WITS_HTTP_INTEGRATION') == '1', 'opt-in WITS HTTP integration')
class WitsHttpIntegration(unittest.TestCase):
    def test_real_bearer_route_union_pagination_exclusion_and_recovery(self):
        wits = Path(os.environ['WITS_SOURCE_ROOT'])
        self.assertEqual(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=wits, text=True).strip(), WITS_REF)
        subprocess.run(['git', 'diff', '--exit-code', 'HEAD', '--', 'app', 'lib', 'prisma'], cwd=wits, check=True, capture_output=True)
        database = os.environ['TEST_DATABASE_URL']
        self.assertTrue(os.environ.get('AM153_DISPOSABLE_DATABASE') == 'synthetic')
        database_binding = urlsplit(database)
        self.assertEqual(database_binding.username, 'synthetic')
        self.assertEqual(database_binding.password, 'synthetic')
        self.assertEqual(database_binding.path, '/synthetic')
        self.assertTrue(database_binding.hostname == 'localhost' or
                        ipaddress.ip_address(database_binding.hostname).is_loopback)
        with tempfile.TemporaryDirectory(prefix='am153-synthetic-') as temporary:
            root = Path(temporary)
            hub, vault, reader, collision = (root / name for name in ('hub', 'vault', 'reader', 'collision'))
            label = label_for([PROJECT_A, PROJECT_B])
            label_ref = {'record_id': label['record_id'], 'revision_digest': revision_digest(label)}
            configure(hub, label)
            tasks = [unique_task_for(label, i) for i in range(501)]
            for task in tasks:
                store_coordination_record(hub, task)
            opened, claimed = claimed_task_for(label)
            store_coordination_record(hub, opened)
            store_coordination_record(hub, claimed)
            hidden = unique_task_for(label, 600)
            hidden.update(originId='44444444-4444-4444-8444-444444444444', projectId=PROJECT_B, projectName='sample-analytics')
            hidden['record_id'] = f"record://coordination/{hidden['originId']}/task/{hidden['taskId']}"
            store_coordination_record(hub, hidden)
            (hub / 'policy/coordination-origin-projects.json').write_bytes(canonical_bytes({
                'schema_id': 'wits/coordination-origin-projects/v0',
                'origins': {tasks[0]['originId']: PROJECT_A, hidden['originId']: PROJECT_B},
            }))
            write_only = label_identity(label_for([]), 'synthetic-write-only')
            write_only['may']['syncTaskPackets'] = [PROJECT_A]
            write_only['may']['syncWorkReceipts'] = [PROJECT_A]
            write_only_ref = {"record_id": write_only["record_id"], "revision_digest": revision_digest(write_only)}
            _write_immutable(hub, _policy_label_path(hub, write_only_ref), canonical_bytes(write_only))
            write_only_principal = 'coordination-principal://synthetic/write-only'
            write_only_token = 'synthetic-am153-write-only'
            writer_token, reader_token = 'synthetic-am153-writer', 'synthetic-am153-reader'
            reader_principal = 'coordination-principal://synthetic/reader-a'
            seed = root / 'synthetic-seed.json'
            seed.write_bytes(canonical_bytes({
                'projects': [{'id': PROJECT_A, 'name': 'sample-service'}, {'id': PROJECT_B, 'name': 'sample-analytics'}],
                'keys': [
                    {'projectId': PROJECT_A, 'token': writer_token, 'principal': PRINCIPAL, 'labelRef': label_ref,
                     'capabilities': [f'coordination:{action}:{PROJECT_A}' for action in ('read', 'sync:task-packet', 'sync:work-receipt')]},
                    {'projectId': PROJECT_A, 'token': write_only_token, 'principal': write_only_principal,
                     'labelRef': write_only_ref, 'capabilities': [f'coordination:{action}:{PROJECT_A}'
                        for action in ('read', 'sync:task-packet', 'sync:work-receipt')]},
                    {'projectId': PROJECT_A, 'token': reader_token, 'principal': reader_principal, 'labelRef': label_ref,
                     'capabilities': [f'coordination:read:{PROJECT_A}']},
                ],
            }))
            # configure() created writer policy; the route rechecks this server-owned binding.
            config = json.loads((hub / 'hub-config.json').read_bytes())
            config['bindings'].append({'session_id': 'coordination-session://synthetic/reader-a',
                'principal_id': reader_principal, 'access_label': label})
            config['bindings'].append({'session_id': 'coordination-session://synthetic/write-only',
                'principal_id': write_only_principal, 'access_label': write_only})
            (hub / 'hub-config.json').write_bytes(canonical_bytes(config))
            env = os.environ | {'DATABASE_URL': database, 'WITS_HTTP_SYNTHETIC_SEED': str(seed),
                'COORDINATION_VAULT_ROOT': str(hub),
                'COORDINATION_SYNC_TOKEN_SECRET': 'synthetic-am153-server-secret-not-a-production-key'}
            script = Path(__file__).parent / 'integration/wits-http-hub.mts'
            log = root / 'server.stderr'
            with log.open('w') as stderr:
                server = subprocess.Popen(['node', '--import', 'tsx', str(script)], cwd=wits,
                    env=env, stdout=subprocess.PIPE, stderr=stderr, text=True)
                try:
                    self.assertTrue(select.select([server.stdout], [], [], 30)[0], 'synthetic WITS server did not start')
                    ready = server.stdout.readline()
                    self.assertTrue(ready, 'synthetic WITS server exited before readiness')
                    url = f"http://127.0.0.1:{json.loads(ready)['port']}"
                    binding = dict(session_id=SESSION, completed_at='ignored', bearer=writer_token,
                        expected_hub_id=HUB_ID, expected_principal_id=PRINCIPAL,
                        expected_access_label_ref=label_ref)
                    new_task = unique_task_for(label, 700)
                    admitted_ref = store_coordination_record(vault, new_task)
                    receipt_ref = store_coordination_record(vault, work_receipt_for(label, claimed))
                    denied = copy.deepcopy(hidden)
                    denied['taskId'] = 'task_' + f'{701:026d}'
                    denied['record_id'] = f"record://coordination/{denied['originId']}/task/{denied['taskId']}"
                    denied_ref = store_coordination_record(vault, denied)
                    def interrupted(response):
                        raise RuntimeError('synthetic interruption before local apply')
                    with self.assertRaisesRegex(RuntimeError, 'synthetic interruption'):
                        sync(vault, url, _before_pull_apply=interrupted, **binding)
                    self.assertFalse((vault / 'generated/coordination-sync/last-successful.json').exists())
                    self.assertTrue((vault / 'generated/coordination-sync/http-pending.json').exists())
                    complete = sync(vault, url, phase='pull', **binding)
                    outcomes = {item['record_ref']['record_id']: item['outcome'] for item in complete['submission_outcomes']}
                    self.assertEqual(outcomes[admitted_ref['record_id']], 'admitted')
                    self.assertEqual(outcomes[receipt_ref['record_id']], 'admitted')
                    self.assertEqual(outcomes[denied_ref['record_id']], 'rejected')
                    self.assertEqual(complete['receipt']['authorized_membership']['page_count'], 2)
                    self.assertEqual(complete['receipt']['excluded_count'], 1)
                    self.assertFalse((vault / 'generated/coordination-sync/http-pending.json').exists())
                    reader.mkdir()
                    restricted = sync(reader, url, phase='pull', **(binding | {
                        'bearer': reader_token, 'expected_principal_id': reader_principal}))
                    serialized = canonical_bytes(restricted)
                    self.assertNotIn(hidden['record_id'].encode(), serialized)
                    self.assertNotIn(b'"mayNot"', serialized)
                    self.assertEqual(restricted['receipt']['excluded_count'], 1)
                    before = directory_digest(reader)
                    self.assertEqual(sync(reader, url, phase='pull', **(binding | {
                        'bearer': reader_token, 'expected_principal_id': reader_principal}))['outcome'], 'no-op')
                    self.assertEqual(directory_digest(reader), before)
                    self.assertEqual(len(load_authorized_projection(reader)), 505)
                    # Denial matrix goes through the actual authenticated POST route.
                    def exchange(token, records):
                        entries = [{'record_ref': {'record_id': r['record_id'],
                            'revision_digest': revision_digest(r)}, 'record': r} for r in records]
                        request = Request(url + '/api/agent/coordination/sync',
                            data=canonical_bytes({'records': entries, 'page_token': None}), method='POST',
                            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
                        with urlopen(request, timeout=20) as response:
                            return json.load(response)
                    withheld_count = exchange(writer_token, [])['receipt']['excluded_count']
                    origin_denials = []
                    for origin in ('55555555-5555-4555-8555-555555555555', hidden['originId']):
                        for identity in (hidden['taskId'], 'task_' + f'{802:026d}'):
                            candidate = unique_task_for(label, 802)
                            candidate.update(originId=origin, taskId=identity)
                            candidate['record_id'] = f'record://coordination/{origin}/task/{identity}'
                            origin_denials.append(candidate)
                    denied_reply = exchange(writer_token, origin_denials)
                    self.assertEqual([o['code'] for o in denied_reply['receipt']['submission_outcomes']],
                                     ['unauthorized-project'] * 4)
                    self.assertEqual(denied_reply['receipt']['excluded_count'], withheld_count)
                    write_only_count = exchange(write_only_token, [])['receipt']['excluded_count']
                    write_only_records = [unique_task_for(write_only, i) for i in (0, 803)]
                    for known in (True, False):
                        candidate = work_receipt_for(write_only, claimed)
                        candidate['writer'] = write_only_principal
                        if not known:
                            candidate['taskRef']['record_id'] = unique_task_for(write_only, 804)['record_id']
                        write_only_records.append(candidate)
                    write_denied = exchange(write_only_token, write_only_records)
                    self.assertEqual([o['code'] for o in write_denied['receipt']['submission_outcomes']],
                                     ['unauthorized-project'] * 4)
                    self.assertEqual(write_denied['receipt']['excluded_count'], write_only_count)
                    self.assertEqual(exchange(writer_token, [])['receipt']['excluded_count'], withheld_count)
                    # A corrupt local pair can be sent for quarantine, never auto-repaired.
                    pair = {'record_id': tasks[0]['record_id'], 'revision_digest': revision_digest(tasks[0])}
                    altered = dict(tasks[0], title='synthetic different bytes')
                    _write_immutable(collision, _record_path(collision, pair), canonical_bytes(altered))
                    quarantined = sync(collision, url, phase='push', **binding)
                    self.assertEqual(quarantined['submission_outcomes'][0]['outcome'], 'quarantined')
                    self.assertFalse((collision / 'generated/coordination-sync/last-successful.json').exists())
                    print('AM153-WITS: admitted=2(task+receipt) rejected=1 quarantined=1 pages=2 excluded=1 retry=verified no-op=verified denials=8(count-invariant)')
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill(); server.wait()
                    server.stdout.close()


if __name__ == '__main__':
    unittest.main()
