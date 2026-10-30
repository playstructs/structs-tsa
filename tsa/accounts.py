"""Restart-safe key creation and the confirmed managed registration lifecycle."""
from contextlib import contextmanager
import fcntl
import json
import re
import os
from pathlib import Path
import tempfile
from urllib.parse import quote
from uuid import UUID

from .durable import private_directory
from .rpc import uint
from .worker import PreparationUnavailable


class Keys:
    def __init__(self, cli):
        self.cli = cli
        self.root = Path(cli.keyring)
        private_directory(self.root)

    @contextmanager
    def lock(self):
        descriptor = os.open(self.root / '.tsa-keyring.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def inventory(self):
        with self.lock():
            keys = self.cli.run([self.cli.binary, 'keys', 'list', *self.cli.flags()])
        if not isinstance(keys, list) or len(keys) > 10000:
            raise PreparationUnavailable('Keyring returned an invalid inventory')
        local = {}
        for key in keys:
            if key.get('type') != 'local':
                continue
            if not isinstance(key.get('address'), str) or not isinstance(key.get('name'), str):
                raise PreparationUnavailable('Keyring identity is malformed')
            # Aliases can share an address. Address-based signing needs one row.
            address, name = key['address'], key['name']
            local[address] = min(name, local.get(address, name))
        return [{'address': address, 'name': local[address]} for address in sorted(local)]

    def backup_path(self, request):
        return self.root / ('request_' + UUID(request['request_id']).hex + '.mnemonic')

    def mnemonic(self, request):
        path = self.backup_path(request)
        if not path.exists() or path.stat().st_mode & 0o077:
            raise PreparationUnavailable('Provisioning key backup is missing or accessible to other users')
        raw = path.read_bytes()
        if not 1 <= len(raw) <= 4096:
            raise PreparationUnavailable('Provisioning key backup is invalid')
        return raw

    def ensure(self, request):
        name = 'tsa_request_' + UUID(request['request_id']).hex
        backup = self.backup_path(request)
        with self.lock():
            try:
                key = self.cli.run([self.cli.binary, 'keys', 'show', name, *self.cli.flags()])
            except PreparationUnavailable:
                key = None
            if key is not None:
                self.mnemonic(request)
                return key['address']
            if not backup.exists():
                # Save entropy durably BEFORE importing into the keyring. A
                # crash at any later point recovers exactly this same key.
                mnemonic = self.cli.run([self.cli.binary, 'keys', 'mnemonic'], json_output=False).encode() + b'\n'
                if not 1 <= len(mnemonic) <= 4096:
                    raise PreparationUnavailable('Mnemonic generation returned invalid output')
                descriptor, temporary = tempfile.mkstemp(prefix='.tsa-mnemonic-', dir=self.root)
                try:
                    with os.fdopen(descriptor, 'wb') as file:
                        file.write(mnemonic)
                        file.flush()
                        os.fsync(file.fileno())
                    os.replace(temporary, backup)
                    directory = os.open(self.root, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            key = self.cli.run([self.cli.binary, 'keys', 'add', name, '--recover', *self.cli.flags()],
                               input=self.mnemonic(request))
            return key['address']

    def proof(self, request, chain_id, nonce):
        return self.cli.run(['structs-sign-proxy', 'address-register', request['player_id'],
                            '--chain-id', chain_id, '--nonce', str(nonce), '--mnemonic-stdin'],
                           input=self.mnemonic(request))

    def guild_proof(self, address, guild_id, nonce):
        with self.lock():
            public = self.cli.run([self.cli.binary, 'keys', 'show', address, *self.cli.flags()])
            if public.get('address') != address or public.get('type') != 'local':
                raise PreparationUnavailable('Role key is not locally available')
            # Cosmos exposes raw export for keyring-only keys whose mnemonic
            # is no longer present. Capture it privately; never put it in argv,
            # an environment variable, a file, or diagnostic output.
            secret = self.cli.run([self.cli.binary, 'keys', 'export', public['name'],
                                   '--unsafe', '--unarmored-hex', '--yes', *self.cli.flags()], json_output=False)
            if not re.fullmatch('[0-9a-fA-F]{64}', secret):
                raise PreparationUnavailable('Keyring proof export did not return a signing key')
            try:
                return self.cli.run(['node', '/opt/structs-sign-proxy/keyring-proof.mjs'], input=json.dumps({
                    'private_key': secret, 'address': address, 'guild_id': guild_id, 'nonce': str(nonce)}).encode())
            finally:
                secret = None


class Accounts:
    def __init__(self, store, node, lcd, keys):
        self.store, self.node, self.lcd, self.keys = store, node, lcd, keys

    def proof_context(self, request):
        height = self.node.height()
        version = self.node.call('abci_info', {}).get('response', {}).get('version')
        if version not in ('0.22.0', 'v0.22.0'):
            raise PreparationUnavailable('Registration requires the verified v0.22.0 protocol')
        address = request['address']
        owner = self.lcd.get('/structs/address/' + quote(address, safe=''), height)
        if owner.get('address') != address or owner.get('playerId') != '':
            raise PreparationUnavailable('Registration address is already associated; resolve its existing attempt')
        nonce = uint(owner.get('proofNonce'))
        proof = self.keys.proof(request, self.node.chain_id, nonce)
        if proof.get('address') != address or proof.get('player_id') != request['player_id'] or proof.get('proof_nonce') != str(nonce):
            raise PreparationUnavailable('Saved provisioning key does not match its requested identity')
        context = {'chain_id': self.node.chain_id, 'protocol': 'v0.22.0', 'source_height': str(height),
                   'player_id': request['player_id'], 'address': address, 'proof_nonce': str(nonce),
                   'registered_player_id': '', 'timeout_height': '0'}
        return proof, context

    def process(self, account_id):
        with self.store.account_lease(account_id) as acquired:
            if not acquired:
                return 'busy'
            request = self.store.account_request(account_id)
            if request is None or request['status'] not in ('generating', 'pending'):
                return 'inactive'
            if request['status'] == 'generating':
                address = self.keys.ensure(request)
                if request['address'] not in (None, address):
                    raise PreparationUnavailable('Keyring and durable key request disagree')
                self.store.bind_account(account_id, address)
                request['address'] = address
                proof, context = self.proof_context(request)
                self.store.register_account(request, proof, context)
                return 'registration-queued'
            tx_id = request['registration_tx_id']
            if self.store.account_ready(account_id, tx_id):
                self.store.activate_account(account_id, tx_id)
                return 'activated'
            if self.store.registration_failed(tx_id):
                proof, context = self.proof_context(request)
                self.store.renew_account(account_id, tx_id, proof, context)
                return 'registration-renewed'
            return 'awaiting-confirmed-registration'
