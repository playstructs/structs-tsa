"""Bounded worker supervision with independent database sessions and recovery."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import signal
from threading import Event, Thread
import time

from .accounts import Accounts, Keys
from .durable import Journal, Volume, write_json
from .inventory import Inventory
from .pools import Pools
from .roles import Roles
from .rpc import Node
from .signer import Cli, Lcd, Signer
from .store import Store
from .worker import Worker


def report(event, **fields):
    # No exception messages, DSNs, CLI output, proofs or secret material.
    print(json.dumps({'event': event, **fields}, separators=(',', ':')), flush=True)


def clients(config):
    node = Node(config.rpc, config.chain_id)
    lcd = Lcd(config.lcd)
    cli = Cli(home=config.home, keyring=config.keyring)
    return node, lcd, cli, Signer(node, lcd, cli, gas_price=config.gas_price)


def reconcile(config):
    store = Store(config.database)
    try:
        node, lcd, cli, _ = clients(config)
        volume = Volume(config.keyring)
        return Inventory(store, node, lcd, Keys(cli), volume, Journal(volume)).run()
    finally:
        store.close()


class Runtime:
    def __init__(self, config):
        self.config = config
        self.stop = Event()
        self.volume = Volume(config.keyring)
        self.health = Path('/run/tsa/health.json')
        self.health.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.inventory_time = 0.0
        self.inventory_ready = False
        self.inventory_error = None

    def process(self, tx_id):
        store = Store(self.config.database)
        try:
            node, _, _, signer = clients(self.config)
            return Worker(store, node, signer, Journal(self.volume)).process(tx_id)
        finally:
            store.close()

    def maintain(self):
        # One maintenance session owns inventory, requested-key generation and
        # pool decisions. Transaction workers continue while it performs I/O.
        store = None
        account_cursor = 0
        role_cursor = 0
        previous_counts = None
        while not self.stop.is_set():
            try:
                if store is None:
                    store = Store(self.config.database)
                    node, lcd, cli, signer = clients(self.config)
                    keys = Keys(cli)
                    inventory = Inventory(store, node, lcd, keys, self.volume, Journal(self.volume), self.stop.is_set)
                    accounts = Accounts(store, node, lcd, keys)
                    roles = Roles(store, node, lcd, keys, self.volume)
                    pools = Pools(store, node, signer, self.volume, self.config.pool_maximum, self.stop.is_set)
                counts = inventory.run()
                self.inventory_error = None
                self.inventory_time = time.time()
                self.inventory_ready = counts.get('ready', 0) > 0
                if counts != previous_counts:
                    report('key-inventory', **counts)
                    previous_counts = counts
                pending = store.account_recovery(account_cursor, limit=4)
                account_cursor = pending[-1] if pending else 0
                requested = store.claim_account()
                if requested is not None:
                    pending.append(requested['id'])
                for account_id in dict.fromkeys(pending):
                    if self.stop.is_set():
                        break
                    try:
                        report('key-request', account_id=account_id, outcome=accounts.process(account_id))
                    except Exception as error:
                        report('key-request-deferred', account_id=account_id, error=type(error).__name__)
                        if store.connection.closed or store.connection.broken:
                            raise
                requested_roles = store.role_recovery(role_cursor, limit=2)
                role_cursor = requested_roles[-1] if requested_roles else 0
                for role_id in requested_roles:
                    if self.stop.is_set():
                        break
                    try:
                        report('role-request', role_id=role_id, outcome=roles.process(role_id))
                    except Exception as error:
                        report('role-request-deferred', role_id=role_id, error=type(error).__name__)
                        if store.connection.closed or store.connection.broken:
                            raise
                if not self.stop.is_set():
                    for account_id in pools.run():
                        report('pool-key-requested', account_id=account_id)
            except Exception as error:
                self.inventory_ready = False
                self.inventory_error = type(error).__name__
                report('maintenance-unavailable', error=self.inventory_error)
                if store is not None:
                    store.close()
                    store = None
            self.stop.wait(10)
        if store is not None:
            store.close()

    def run(self):
        for name in (signal.SIGTERM, signal.SIGINT):
            signal.signal(name, lambda *_: self.stop.set())
        node, _, cli, _ = clients(self.config)
        if cli.run([cli.binary, 'version'], json_output=False) != '0.22.0':
            raise ValueError('The worker requires its pinned v0.22.0 signing binary')
        maintenance = Thread(target=self.maintain, name='tsa-maintenance')
        maintenance.start()
        store = None
        cursor = 0
        futures = {}
        try:
            with ThreadPoolExecutor(max_workers=self.config.workers, thread_name_prefix='tsa-tx') as executor:
                while not self.stop.is_set():
                    for tx_id, future in list(futures.items()):
                        if future.done():
                            del futures[tx_id]
                            try:
                                outcome = future.result()
                                report('transaction', tx_id=tx_id, outcome=outcome)
                            except Exception as error:
                                report('transaction-deferred', tx_id=tx_id, error=type(error).__name__)
                    try:
                        if store is None:
                            store = Store(self.config.database)
                            store.scalar("SELECT 'signer.claim_transaction_v022(uuid)'::regprocedure::text")
                        free = self.config.workers - len(futures)
                        # Give both recovery and new work capacity each pass.
                        recover = store.recovery(cursor, max(1, (free + 1) // 2)) if free else []
                        if free:
                            cursor = recover[-1] if recover else 0
                        for tx_id in recover:
                            if tx_id not in futures:
                                futures[tx_id] = executor.submit(self.process, tx_id)
                        if time.time() - self.inventory_time < 120:
                            for _ in range(self.config.workers - len(futures)):
                                if self.stop.is_set():
                                    break
                                claim = store.claim(self.volume.inventory_id)
                                if claim is None:
                                    break
                                tx_id = claim['transaction']['id']
                                futures[tx_id] = executor.submit(self.process, tx_id)
                        write_json(self.health, {'heartbeat': time.time(), 'inventory': self.inventory_time,
                                                'state': 'running', 'ready': self.inventory_ready, 'inventory_error': self.inventory_error, 'workers': len(futures)})
                    except Exception as error:
                        report('database-unavailable', error=type(error).__name__)
                        if store is not None:
                            store.close()
                            store = None
                        write_json(self.health, {'heartbeat': time.time(), 'state': 'waiting-database'})
                    self.stop.wait(2)
        finally:
            self.stop.set()
            maintenance.join()
            if store is not None:
                store.close()
            write_json(self.health, {'heartbeat': time.time(), 'state': 'stopped'})
