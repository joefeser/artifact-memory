#!/usr/bin/env python3
"""Provision only an owned synthetic container for the pinned WITS route proof."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

WITS_REF = 'd07f850d07a447e7672ae40a0e61b67029e71d02'
IMAGE = 'pgvector/pgvector:pg16@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b'


def main():
    for executable in ('docker', 'node', 'git'):
        if shutil.which(executable) is None:
            raise RuntimeError('required integration runtime is unavailable: ' + executable)
    wits = Path(os.environ['WITS_SOURCE_ROOT']).resolve()
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=wits, text=True).strip() != WITS_REF:
        raise RuntimeError('WITS source does not match the pinned merged ref')
    subprocess.run(['git', 'diff', '--exit-code', 'HEAD', '--', 'app', 'lib', 'prisma'], cwd=wits,
                   check=True, capture_output=True)
    prisma = wits / 'node_modules/prisma/build/index.js'
    if not prisma.is_file():
        raise RuntimeError('pinned WITS dependencies must be installed')
    # Never consume TEST_DATABASE_URL or touch an existing container/database.
    container = None
    with tempfile.TemporaryFile() as log:
        try:
            name = 'am153-synthetic-' + uuid.uuid4().hex
            container = subprocess.check_output(['docker', 'run', '-d', '--name', name,
                '--label', 'artifact-memory.synthetic=am153', '-e', 'POSTGRES_USER=synthetic',
                '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_DB=synthetic',
                '-p', '127.0.0.1::5432', IMAGE], stderr=log, text=True, env=os.environ | {'POSTGRES_PASSWORD': 'synthetic'}).strip()
            deadline = time.monotonic() + 60
            while subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'synthetic',
                                  '-d', 'synthetic'], stdout=log, stderr=log).returncode:
                if time.monotonic() >= deadline:
                    raise RuntimeError('synthetic database readiness timed out')
                time.sleep(0.5)
            ports = json.loads(subprocess.check_output(['docker', 'inspect', '--format',
                '{{json .NetworkSettings.Ports}}', container], text=True))
            port = ports['5432/tcp'][0]['HostPort']
            database = f'postgresql://synthetic:synthetic@127.0.0.1:{port}/synthetic'
            env = os.environ | {'DATABASE_URL': database, 'TEST_DATABASE_URL': database,
                'RUN_WITS_HTTP_INTEGRATION': '1', 'AM153_DISPOSABLE_DATABASE': 'synthetic',
                'WITS_SOURCE_ROOT': str(wits)}
            for command in ('db', 'generate'):
                args = ['node', str(prisma), command] + (['push'] if command == 'db' else [])
                subprocess.run(args, cwd=wits, env=env, stdout=log, stderr=log, check=True, timeout=120)
            subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_coordination_http_wits', '-v'],
                           cwd=Path(__file__).resolve().parents[1], env=env, check=True, timeout=180)
        finally:
            if container:
                subprocess.run(['docker', 'rm', '-f', container], stdout=log, stderr=log, check=True)
    print('AM153 fixture: provisioned=verified cleanup=verified')


if __name__ == '__main__':
    try:
        main()
    except (KeyError, OSError, RuntimeError, subprocess.SubprocessError):
        print('WITS HTTP proof setup or test failed; no acceptance claim', file=sys.stderr)
        sys.exit(1)
