"""Create two isolated PG instances, migrate them, run real TSA recovery, clean up."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--schema', type=Path, default=root.parent / 'structs-pg')
parser.add_argument('--image', default='structs-v022-tsa-candidate:development')
args = parser.parse_args()
schema = args.schema.resolve()
label = subprocess.check_output(['docker', 'inspect', '--format', '{{index .Config.Labels "structs.task"}}', 'structs-v022-pg'], text=True).strip()
if label != 'v022-integration':
    raise RuntimeError('Source PostgreSQL must carry the disposable-test label')
image = subprocess.check_output(['docker', 'inspect', '--format', '{{.Image}}', 'structs-v022-pg'], text=True).strip()
network = 'structs-v022-tsa-' + uuid4().hex[:10]
containers = []
try:
    subprocess.run(['docker', 'network', 'create', '--internal', '--label', 'structs.task=v022-tsa-test', network], check=True, capture_output=True)
    for alias in ('tsa-first', 'tsa-second'):
        name = network + '-' + alias
        subprocess.run(['docker', 'run', '-d', '--pull=never', '--name', name, '--network', network,
                        '--network-alias', alias, '--label', 'structs.task=v022-tsa-test',
                        '-v', str(schema) + ':/migration:ro', '--entrypoint', '/usr/bin/pg_ctlcluster',
                        image, '--foreground', '18', 'main', 'start'], check=True, capture_output=True)
        containers.append(name)
        command = ['docker', 'exec', '--user', 'structs', '-e', 'PGHOST=/var/run/postgresql', '-e',
                   'PGOPTIONS=-c structs.ledger_writer_contract=denomination-v1 -c structs.signer_contract=v022-1',
                   '-w', '/migration', name]
        for _ in range(60):
            if subprocess.run(command + ['pg_isready', '-d', 'structs'], capture_output=True).returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Disposable PostgreSQL startup timed out')
        migration = subprocess.run(command + ['sqitch', 'deploy', '--verify', 'db:pg:structs'], capture_output=True, text=True, timeout=300)
        if migration.returncode:
            raise RuntimeError(migration.stdout + migration.stderr)
        # These containers have no published ports and share only this internal
        # test network. Permit the fixture worker's database connection there.
        subnet = json.loads(subprocess.check_output(['docker', 'network', 'inspect', network], text=True))[0]['IPAM']['Config'][0]['Subnet']
        subprocess.run(['docker', 'exec', '-i', name, 'tee', '-a', '/etc/postgresql/18/main/pg_hba.conf'],
            input='\nhost structs structs,structs_tsa ' + subnet + ' trust\n', text=True, check=True, capture_output=True)
        subprocess.run(['docker', 'exec', name, 'pg_ctlcluster', '18', 'main', 'reload'], check=True, capture_output=True)
        print(alias + ': full Sqitch deploy and verify passed', flush=True)
    result = subprocess.run(['docker', 'run', '--rm', '--network', network, '--platform', 'linux/amd64',
        '--label', 'structs.task=v022-tsa-test', '-v', str(root) + ':/workspace:ro', '-v', str(schema) + ':/schema:ro',
        '-e', 'PYTHONPATH=/opt/tsa', '-e', 'TSA_DISPOSABLE_TEST=v022-integration',
        '-e', 'DATABASE_URL=postgres://structs@tsa-first:5432/structs',
        '-e', 'TSA_REBUILT_DATABASE_URL=postgres://structs@tsa-second:5432/structs',
        '-w', '/workspace', '--entrypoint', 'python', args.image,
        'tests/database_integration.py'], capture_output=True, text=True, timeout=240)
    print(result.stdout, end='')
    if result.returncode:
        raise RuntimeError(result.stderr)
finally:
    for name in containers:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30)
    subprocess.run(['docker', 'network', 'rm', network], capture_output=True, timeout=30)
