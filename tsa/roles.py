"""Fulfil existing onboarding requests; never create roles because of queue load."""
import hashlib
import json
from urllib.parse import quote

from .durable import private_directory, write_json
from .rpc import uint
from .worker import PreparationUnavailable


class Roles:
    PRIMARY_PERMISSIONS = 33554431  # New-player primary grant fixed by v0.22.

    def __init__(self, store, node, lcd, keys, volume):
        self.store, self.node, self.lcd, self.keys, self.volume = store, node, lcd, keys, volume
        self.root = volume.root / 'role-keys'
        private_directory(self.root)

    def key_for(self, request):
        # Stable application identity survives SQL numeric IDs and request UUIDs
        # being recreated after a volume reset. The existing key is reused only
        # for the exact same guild/name intent; no grant is inferred here.
        identity = {'guild_id': request['guild_id'], 'username': request['username']}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        path = self.root / (digest + '.json')
        with self.volume.lock('role-keys'):
            saved = json.loads(path.read_text()) if path.exists() else None
            if saved is not None and saved['identity'] != identity:
                raise PreparationUnavailable('Saved role key belongs to another onboarding request')
            if request['address'] is not None:
                address = request['address']
                if saved is not None and saved.get('address') not in (None, address):
                    raise PreparationUnavailable('Saved role key differs from its existing account')
                public = self.keys.cli.run([self.keys.cli.binary, 'keys', 'show', address, *self.keys.cli.flags()])
                if public.get('address') != address or public.get('type') != 'local':
                    raise PreparationUnavailable('Existing role key is not locally available')
                if saved is None:
                    write_json(path, {'identity': identity, 'address': address})
                return address
            if saved is None:
                saved = {'identity': identity, 'request_id': request['request_id']}
                write_json(path, saved)
            if saved.get('address') is not None:
                public = self.keys.cli.run([self.keys.cli.binary, 'keys', 'show', saved['address'], *self.keys.cli.flags()])
                if public.get('address') != saved['address'] or public.get('type') != 'local':
                    raise PreparationUnavailable('Saved role key is not locally available')
                return saved['address']
            address = self.keys.ensure(saved)
            write_json(path, dict(saved, address=address))
            return address

    def process(self, role_id):
        with self.store.role_lease(role_id) as acquired:
            if not acquired:
                return 'busy'
            request = self.store.prepare_role(role_id, self.PRIMARY_PERMISSIONS)
            if request is None or request['activated']:
                return 'inactive'
            context = self.store.readiness()
            if context.get('transaction_ready') is not True or context.get('protocol') != 'v0.22.0':
                return 'waiting-index'
            if self.node.call('abci_info', {}).get('response', {}).get('version') not in ('0.22.0', 'v0.22.0'):
                raise PreparationUnavailable('Key activation requires the verified v0.22.0 protocol')
            height = uint(context['indexed_height'])
            tip = self.node.height()
            if not height <= tip <= height + 5:
                return 'waiting-index'
            address = self.key_for(request)
            path = '/structs/address/' + quote(address, safe='')
            current = self.lcd.get(path, tip)
            if current.get('address') != address:
                raise PreparationUnavailable('Role proof address differs from the requested key')
            player = current.get('playerId')
            if player:
                indexed = self.lcd.get(path, height) if height != tip else current
                if indexed.get('playerId') != player or uint(current.get('permissions')) != self.PRIMARY_PERMISSIONS \
                        or indexed.get('permissions') != current.get('permissions'):
                    return 'waiting-role-registration'
                if self.store.activate_role(role_id, request['request_id'], player, height, tip):
                    return 'activated'
                return 'waiting-confirmed-role'
            # An unregistered address has no player proxy nonce; v0.22 derives
            # the guild-join proof nonce from player index zero, which is zero.
            # This is distinct from address-register's address proof nonce.
            proof = self.keys.guild_proof(address, request['guild_id'], 0)
            if proof.get('address') != address or proof.get('guild_id') != request['guild_id'] or proof.get('nonce') != '0':
                raise PreparationUnavailable('Role proof does not match its requested identity')
            result = self.store.bind_role(role_id, request['request_id'], address, proof)
            return 'waiting-external-proxy' if result['external_requested'] else 'waiting-proxy-transaction'
