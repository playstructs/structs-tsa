"""Real SQL and release CLI, with a local RPC fixture; never a live chain.

Run inside a disposable container sharing only the labelled test PG network.
The harness creates two fresh disposable instances and migrates each through
the complete Sqitch plan. Both are removed on completion.
"""
from concurrent.futures import ThreadPoolExecutor
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import tempfile
from threading import Thread
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tsa.accounts import Keys
from tsa.durable import Journal, Volume
from tsa.inventory import Inventory
from tsa.rpc import Node, tx_hash
from tsa.roles import Roles
from tsa.signer import Cli, Lcd, Signer
from tsa.store import Store
from tsa.worker import Worker


class Chain:
    chain_id = 'structstestnet-111'
    height = 3353000
    broadcasts = 0
    lose_response = False
    primary_ready = False
    owners = {}
    transactions = {}

    @classmethod
    def commit_all(cls):
        for item in cls.transactions.values():
            item['committed'] = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, body, height=None):
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        if height is not None:
            self.send_header('grpc-metadata-x-cosmos-block-height', str(height))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        address = self.path.rsplit('/', 1)[-1]
        height = self.headers['x-cosmos-block-height']
        if self.path.endswith('/cosmos/base/tendermint/v1beta1/node_info'):
            self.reply({'default_node_info': {'network': Chain.chain_id},
                        'application_version': {'version': '0.22.0'}}, height)
        elif self.path.startswith('/structs/address/'):
            player, permissions = Chain.owners.get(address, ('', 0))
            self.reply({'address': address, 'playerId': player, 'permissions': str(permissions), 'proofNonce': '0'}, height)
        else:
            self.reply({'account': {'@type': '/cosmos.auth.v1beta1.BaseAccount', 'address': address,
                                  'account_number': '1', 'sequence': '0'}}, height)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        method, params = request['method'], request['params']
        error = None
        if method == 'status':
            result = {'node_info': {'network': Chain.chain_id},
                      'sync_info': {'latest_block_height': str(Chain.height),
                                    'catching_up': self.path == '/primary' and not Chain.primary_ready}}
        elif method == 'abci_info':
            result = {'response': {'version': '0.22.0'}}
        elif method == 'abci_query':
            assert params['path'] == '/app/simulate'
            result = {'response': {'code': 0, 'height': params['height'], 'value': base64.b64encode(
                json.dumps({'gas_info': {'gas_used': '100000'}}).encode()).decode()}}
        elif method == 'broadcast_tx_sync':
            raw = base64.b64decode(params['tx'])
            digest = tx_hash(raw)
            Chain.broadcasts += 1
            Chain.transactions[digest] = {'raw': raw, 'height': Chain.height + 1,
                                          'committed': not Chain.lose_response}
            if Chain.lose_response:
                self.close_connection = True
                return
            result = {'hash': digest, 'code': 0, 'codespace': '', 'log': ''}
        elif method == 'tx':
            digest = base64.b64decode(params['hash']).hex().upper()
            item = Chain.transactions.get(digest)
            if item is None or not item['committed']:
                error = {'code': -32603, 'message': 'Internal error', 'data': 'tx (' + digest + ') not found'}
                result = None
            else:
                result = {'hash': digest, 'height': str(item['height']), 'index': 0,
                          'tx': base64.b64encode(item['raw']).decode(), 'tx_result': {'code': 0, 'codespace': '', 'log': ''}}
        elif method == 'block':
            item = next(value for value in Chain.transactions.values() if value['height'] == int(params['height']) and value['committed'])
            result = {'block_id': {'hash': 'A' * 64}, 'block': {
                'header': {'chain_id': Chain.chain_id, 'height': params['height']},
                'data': {'txs': [base64.b64encode(item['raw']).decode()]}}}
        elif method == 'block_results':
            result = {'height': params['height'], 'txs_results': [{'code': 0, 'codespace': '', 'log': ''}]}
        else:
            raise AssertionError('Unexpected RPC method ' + method)
        self.reply({'jsonrpc': '2.0', 'id': 'tsa', **({'error': error} if error else {'result': result})})


def first_role_bootstrap(dsns, node, lcd):
    # No operator-generated seed key: use the pending request created when a
    # guild is indexed. Repeat after SQL loss with the same durable key volume.
    with tempfile.TemporaryDirectory(prefix='tsa-first-role-test-') as root:
        cli = Cli(home=root + '/home', keyring=root + '/keys')
        keys = Keys(cli)
        volume = Volume(cli.keyring)
        address = None
        previous_request = None
        for dsn in dsns:
            store = Store(dsn)
            try:
                with store.connection.transaction(force_rollback=True):
                    store.connection.execute(Path('/schema/tests/fixtures/v022-signer.sql').read_text(), prepare=False)
                    # No established guild signer exists on a first install.
                    store.connection.execute('DELETE FROM signer.account')
                    role_id = store.scalar("SELECT role_id FROM structs.player_internal_pending WHERE guild_id='0-990940'")
                    store.connection.execute('SET LOCAL ROLE structs_tsa')
                    inventory = Inventory(store, node, lcd, keys, volume, Journal(volume))
                    expected = {'known': 0} if address is None else {'known': 1, 'unregistered': 1}
                    assert inventory.run() == expected
                    assert role_id in store.role_recovery()
                    roles = Roles(store, node, lcd, keys, volume)
                    assert roles.process(role_id) == 'waiting-external-proxy'
                    request = store.prepare_role(role_id, Roles.PRIMARY_PERMISSIONS)
                    assert request['external_requested'] and request['proxy_tx_id'] is None
                    assert request['request_id'] != previous_request
                    previous_request = request['request_id']
                    if address is not None:
                        assert request['address'] == address, 'SQL reconstruction replaced a surviving role key'
                    address = request['address']
                    assert len(keys.inventory()) == 1
                    # Repeated processing and a reconstructed worker retain the
                    # exact key/proof request and never broadcast the first role.
                    restarted = Roles(store, node, lcd, Keys(cli), Volume(cli.keyring))
                    assert restarted.process(role_id) == 'waiting-external-proxy'
                    assert store.prepare_role(role_id, Roles.PRIMARY_PERMISSIONS) == request
                    assert store.scalar('SELECT count(*) FROM signer.tx') == 0
                    assert store.scalar('SELECT count(*) FROM signer.account') == 1
                    Chain.owners[address] = ('1-990943', Roles.PRIMARY_PERMISSIONS)
                    assert restarted.process(role_id) == 'waiting-confirmed-role'
                    store.connection.execute('RESET ROLE')
                    store.connection.execute("INSERT INTO structs.player(id,primary_address,guild_id) VALUES('1-990943',%s,'0-990940')", (address,))
                    store.connection.execute("""INSERT INTO structs.permission(id,object_type,object_index,object_id,player_id,val)
                        VALUES('8-' || %s || '@0','address',%s,'1-990943','1-990943',33554431)""", (address, address))
                    store.connection.execute('SET LOCAL ROLE structs_tsa')
                    assert restarted.process(role_id) == 'activated'
                    assert inventory.run() == {'known': 1, 'ready': 1}
                    assert restarted.process(role_id) == 'inactive'
                    assert Chain.broadcasts == 0
                Chain.owners.pop(address)
            finally:
                store.close()


def main():
    if os.environ.get('TSA_DISPOSABLE_TEST') != 'v022-integration':
        raise RuntimeError('Disposable test acknowledgement is required')
    first_dsn = os.environ['DATABASE_URL']
    second_dsn = os.environ['TSA_REBUILT_DATABASE_URL']
    if urlsplit(first_dsn).hostname != 'tsa-first' or urlsplit(second_dsn).hostname != 'tsa-second':
        raise RuntimeError('Only the isolated harness database hosts are allowed')
    store = None
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = 'http://127.0.0.1:' + str(server.server_port)
    try:
        first_role_bootstrap((first_dsn, second_dsn), Node(url, Chain.chain_id), Lcd(url))
        print('Fresh role: empty keyring, external approval, restart and SQL reconstruction passed', flush=True)
        with tempfile.TemporaryDirectory(prefix='tsa-database-test-') as root:
            # Match the pre-v022 image's actual volume layout. Both the Python
            # inventory and the packaged daemon must find these keys in place.
            legacy_home = Path(root) / 'legacy-home'
            legacy_home.mkdir(mode=0o700)
            key_directory = Path(root) / 'keys'
            key_directory.mkdir(mode=0o700)
            (legacy_home / 'keyring-test').symlink_to(key_directory, target_is_directory=True)
            cli = Cli(home=root + '/home', keyring=root + '/keys')
            keys = Keys(cli)
            addresses = [cli.run(['structsd', 'keys', 'add', label, '--home', str(legacy_home),
                                 '--keyring-backend', 'test', '--output', 'json'])['address']
                         for label in ('account_legacy', 'another-local-name', 'tsa_unknown')]
            Chain.owners = {addresses[0]: ('1-990940', 33554431), addresses[1]: ('1-990940', 16)}
            fixture = Path('/schema/tests/fixtures/v022-signer.sql').read_text()
            fixture = fixture.replace('queuekeya', addresses[0]).replace('queuerestricted', addresses[1])
            volume = Volume(cli.keyring)
            journal = Journal(volume)
            node, lcd = Node(url, Chain.chain_id), Lcd(url)
            signer = Signer(node, lcd, cli)
            def seed():
                store.connection.execute(fixture, prepare=False)
                # Inserting a guild legitimately creates its initial onboarding
                # request. This recovery scenario has no new role requests.
                store.connection.execute("""WITH pending AS (DELETE FROM structs.player_internal_pending
                    WHERE guild_id='0-990940' RETURNING role_id) DELETE FROM signer.role WHERE id IN (SELECT role_id FROM pending)""")
                store.connection.execute("DELETE FROM signer.account WHERE role_id=990940")
                store.connection.execute("DELETE FROM signer.role WHERE id=990940")
            store = Store(first_dsn)
            seed()
            inventory = Inventory(store, node, lcd, keys, volume, journal)
            store.connection.execute('SET ROLE structs_tsa')
            counts = inventory.run()
            assert counts == {'known': 3, 'ready': 2, 'unregistered': 1}, counts
            store.connection.execute('RESET ROLE')
            store.scalar("SELECT signer.tx_player_update_name('1-990940','worker integration')")
            store.connection.execute('SET ROLE structs_tsa')
            claim = store.claim(volume.inventory_id)
            assert claim is not None
            tx_id = claim['transaction']['id']
            worker = Worker(store, node, signer, journal)
            assert worker.process(tx_id) == 'accepted'
            assert store.submission(tx_id)['state'] == 'accepted'
            assert len(journal.unresolved()) == 1
            assert Worker(store, node, signer, Journal(Volume(cli.keyring))).process(tx_id) == 'committed'
            assert not journal.unresolved()
            assert Chain.broadcasts == 1
            # A second exact identity receives no response. Destroy all SQL
            # state, retaining only the volume and the independently indexed
            # chain fixture, exactly the user's stack reconstruction scenario.
            Chain.height += 1
            Chain.lose_response = True
            store.connection.execute('RESET ROLE')
            store.scalar("SELECT signer.tx_player_update_name('1-990940','unknown before database rebuild')")
            store.connection.execute('SET ROLE structs_tsa')
            claim = store.claim(volume.inventory_id)
            assert worker.process(claim['transaction']['id']) == 'unknown'
            assert Chain.broadcasts == 2
            # Concurrent pool managers cannot consume the last slot twice;
            # generated claims still come only from the explicit request.
            store.connection.execute('RESET ROLE')
            store.scalar("SELECT signer.tx_player_update_name('1-990940','pending_pool_work')")
            store.connection.execute('SET ROLE structs_tsa')
            candidate = store.pool_candidates(volume.inventory_id)['candidates'][0]
            intent = {'role_id': candidate['account']['role_id'], 'source_account_id': candidate['account']['id'],
                'tx_id': candidate['transaction']['id'], 'permissions': candidate['permissions'],
                'max_accounts': 3, 'source_context': candidate['source_context']}
            def pool_request():
                connection = Store(first_dsn)
                try:
                    connection.connection.execute('SET ROLE structs_tsa')
                    return connection.request_pool_account(volume.inventory_id, dict(intent, request_id=str(uuid4())))
                finally:
                    connection.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: pool_request(), range(2)))
            assert sum(item is not None for item in results) == 1, results
            assert store.scalar('SELECT count(*) FROM signer.account WHERE role_id=%s', (intent['role_id'],)) == 3
            def generation_claim():
                connection = Store(first_dsn)
                try:
                    connection.connection.execute('SET ROLE structs_tsa')
                    return connection.claim_account()
                finally:
                    connection.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(pool.map(lambda _: generation_claim(), range(2)))
            assert sum(item is not None for item in claims) == 1, claims
            store.close()
            store = None
            store = Store(second_dsn)
            seed()
            reopened = Journal(Volume(cli.keyring))
            store.connection.execute('SET ROLE structs_tsa')
            inventory = Inventory(store, node, lcd, keys, volume, reopened)
            counts = inventory.run()
            assert counts == {'known': 3, 'held': 1, 'ready': 1, 'unregistered': 1}, counts
            assert store.scalar('SELECT count(*) FROM signer.tx') == 0
            Chain.commit_all()
            counts = inventory.run()
            assert counts == {'known': 3, 'ready': 2, 'unregistered': 1}, counts
            assert not reopened.unresolved()
            assert Chain.broadcasts == 2
            assert store.scalar('SELECT count(*) FROM signer.tx') == 0
            assert store.scalar("SELECT count(*) FROM signer.role WHERE player_id='1-990940'") == 1
            ids = store.scalar("SELECT jsonb_agg(id ORDER BY id) FROM signer.account WHERE address=ANY(%s)", (addresses,))
            inventory.run()
            assert ids == store.scalar("SELECT jsonb_agg(id ORDER BY id) FROM signer.account WHERE address=ANY(%s)", (addresses,))
            # Start the real supervisor under its dedicated login, observe its
            # health and SIGTERM exit. It must not invent work after SQL reset.
            environment = dict(os.environ, DATABASE_URL=make_conninfo(second_dsn, user='structs_tsa'),
                TSA_RPC_URL=url+'/primary', TSA_LCD_URL=url,
                TSA_RPC_FALLBACK_URL=url, TSA_LCD_FALLBACK_URL=url,
                TSA_HOME=cli.home, TSA_KEYRING_DIR=cli.keyring,
                TSA_WORKERS='2', TSA_ROLE_MAX_KEYS='40')
            health = Path('/run/tsa/health.json')
            health.unlink(missing_ok=True)
            with tempfile.TemporaryFile() as output:
                process = subprocess.Popen([sys.executable, '-m', 'tsa'], env=environment, stdout=output, stderr=output)
                try:
                    deadline = time.monotonic() + 60
                    while True:
                        if process.poll() is not None:
                            output.seek(0)
                            raise AssertionError(output.read().decode())
                        if health.exists():
                            status = json.loads(health.read_text())
                            if status.get('ready') is True:
                                break
                        assert time.monotonic() < deadline, 'Supervisor did not establish healthy inventory'
                        time.sleep(.2)
                    checked = subprocess.run([sys.executable, '-m', 'tsa', 'health'], env=environment, capture_output=True)
                    assert checked.returncode == 0, 'Container healthcheck rejected the running supervisor'
                    assert json.loads(checked.stdout)['endpoint'] == 'fallback', checked.stdout
                    Chain.primary_ready = True
                    deadline = time.monotonic() + 60
                    while True:
                        status = json.loads(health.read_text())
                        if status.get('ready') is True and status.get('endpoint', {}).get('mode') == 'primary':
                            break
                        assert process.poll() is None, 'Supervisor exited during endpoint recovery'
                        assert time.monotonic() < deadline, 'Supervisor did not recover to primary'
                        time.sleep(.2)
                    checked = subprocess.run([sys.executable, '-m', 'tsa', 'health'], env=environment, capture_output=True)
                    assert checked.returncode == 0 and json.loads(checked.stdout)['endpoint'] == 'primary', checked.stdout
                    process.terminate()
                    assert process.wait(timeout=30) == 0
                    assert json.loads(health.read_text())['state'] == 'stopped'
                    assert Chain.broadcasts == 2
                    assert store.scalar('SELECT count(*) FROM signer.tx') == 0
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
            print(json.dumps({'real_sql': True, 'actual_release_cli': '0.22.0', 'rpc': 'local fixture',
                              'broadcasts_to_fixture': 2, 'live_broadcasts': 0, 'recovered_database': True,
                              'held_unknown_send': True, 'daemon_health_and_shutdown': True,
                              'daemon_fallback_and_primary_recovery': True,
                              'concurrent_last_slot_and_generation_claim': True, 'dedicated_database_login': True, 'no_duplicate_send_or_queue': True, 'result': 'passed'}))
    finally:
        if store is not None:
            store.close()
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
