"""Crash-safe files on the same persistent volume as the signing keyring."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
from uuid import UUID, uuid4

from .rpc import RpcError, tx_hash
from .worker import submission


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def private_directory(path):
    path = Path(path)
    if not path.exists():
        private_directory(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)
        # The directory entry itself must survive a power loss before any
        # transaction is allowed to depend on files inside it.
        sync_directory(path.parent)
    return path


def write_json(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.tsa-write-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as file:
            json.dump(value, file, separators=(',', ':'))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Volume:
    def __init__(self, keyring):
        self.root = Path(keyring) / 'tsa-v022'
        private_directory(self.root)
        with self.lock('identity'):
            identity = self.root / 'inventory.json'
            if not identity.exists():
                write_json(identity, {'inventory_id': str(uuid4())})
            self.inventory_id = str(UUID(json.loads(identity.read_text())['inventory_id']))

    @contextmanager
    def lock(self, name):
        descriptor = os.open(self.root / (name + '.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)


class Journal:
    def __init__(self, volume):
        self.volume = volume
        self.root = volume.root / 'outbox'
        private_directory(self.root)
        self.pending = self.root / 'pending'
        private_directory(self.pending)
        self.completed = self.root / 'completed'
        private_directory(self.completed)
        self.cursor = 0

    def begin(self, claim, saved):
        # This marker precedes the SQL send permit and every network write. If
        # the database is subsequently destroyed, a surviving uncertain marker
        # keeps the key held. It is never permission to re-create a queue row.
        digest = saved['tx_hash']
        if tx_hash(saved['raw']) != digest:
            raise ValueError('Invalid journal transaction identity')
        identity = {name: saved[name] for name in ('tx_id', 'claim_token', 'tx_hash', 'signed_bytes',
                    'account_number', 'sequence', 'source_height', 'timeout_height')}
        identity.update(address=claim['account']['address'], chain_id=claim['transaction']['chain_id'])
        path = self.pending / (digest + '.json')
        with self.volume.lock('outbox'):
            if (self.completed / path.name).exists():
                raise ValueError('A completed transaction cannot acquire another send permit')
            if path.exists():
                if json.loads(path.read_text()) != identity:
                    raise ValueError('Existing journal identity differs from the saved transaction')
            else:
                write_json(path, identity)

    def finish(self, saved, result):
        if result.get('hash') != saved['tx_hash'] or not (result.get('stage') == 'deliver_tx'
                or result.get('stage') == 'check_tx' and result.get('code') not in (None, '0')
                or result.get('stage') == 'unsent' and result.get('code') == 'cancelled'):
            raise ValueError('Journal completion needs a definitive matching outcome')
        name = saved['tx_hash'] + '.json'
        with self.volume.lock('outbox'):
            path = self.pending / name
            if not path.exists():
                return
            record = json.loads(path.read_text())
            write_json(self.completed / name, dict(record, result=result))
            path.unlink()
            sync_directory(self.pending)

    def unresolved(self):
        # Only unresolved sends are scanned; historical completions never grow
        # the recovery loop. Malformed journal files fail closed at startup.
        records = []
        with self.volume.lock('outbox'):
            for path in sorted(self.pending.glob('*.json')):
                saved = submission(json.loads(path.read_text()))
                if path.name != saved['tx_hash'] + '.json':
                    raise ValueError('Journal file name differs from its transaction identity')
                completed = self.completed / path.name
                if completed.exists():
                    # Completion was fsynced before removing the pending file.
                    result = json.loads(completed.read_text())
                    if any(result.get(key) != value for key, value in saved.items() if key != 'raw'):
                        raise ValueError('Conflicting journal completion')
                    path.unlink()
                    sync_directory(self.pending)
                    continue
                records.append(saved)
        return records

    def observe(self, node, store=None, limit=32):
        records = self.unresolved()
        held = {saved['tx_hash']: saved['address'] for saved in records}
        if not records:
            return set()
        start = self.cursor % len(records)
        batch = (records[start:] + records[:start])[:limit]
        self.cursor = (start + len(batch)) % len(records)
        for saved in batch:
            if saved['chain_id'] != node.chain_id:
                continue
            database = store.matching_submission(saved) if store is not None else None
            if database is not None:
                state = database['state']
                if state in ('committed', 'rejected', 'cancelled'):
                    result = database['deliver_tx'] if state == 'committed' else database['check_tx']
                    if state == 'cancelled':
                        result = {'stage': 'unsent', 'code': 'cancelled', 'hash': saved['tx_hash']}
                    self.finish(saved, result)
                    held.pop(saved['tx_hash'], None)
                    continue
                if database.get('account_reserved') is True:
                    # SQL still owns this exact outstanding identity. It keeps
                    # the account signing; reload must not turn a normal busy
                    # key into an orphan or exclude it from pool planning.
                    held.pop(saved['tx_hash'], None)
                    continue
            try:
                result = node.committed(saved)
            except RpcError:
                continue
            if result is not None:
                self.finish(saved, result)
                held.pop(saved['tx_hash'], None)
        return set(held.values())
