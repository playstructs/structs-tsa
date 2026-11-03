"""Queue pressure requests explicit same-grant keys; claims have no side effects."""
import json
from uuid import uuid4

from .durable import private_directory, write_json
from .rpc import RpcError, uint
from .worker import InvalidRequest, PreparationUnavailable


class Pools:
    def __init__(self, store, node, signer, volume, maximum=40, stopping=lambda: False):
        if type(maximum) is not int or not 1 <= maximum <= 40:
            raise ValueError('Role key maximum must be between 1 and 40')
        self.store, self.node, self.signer, self.volume = store, node, signer, volume
        self.maximum = maximum
        self.stopping = stopping
        self.cursor = 0
        self.root = volume.root / 'pool-requests'
        private_directory(self.root)

    def submit(self, path, intent):
        result = self.store.request_pool_account(self.volume.inventory_id, intent)
        # A lost DB acknowledgement leaves the same UUID on the volume. Retry
        # that identity before considering any further growth for this role.
        write_json(path, dict(intent, resolved=True, account_id=result['id'] if result else None))
        return result

    def run(self):
        created = []
        with self.volume.lock('pool-manager'):
            unresolved_roles = set()
            for path in sorted(self.root.glob('*.json')):
                if self.stopping():
                    return created
                intent = json.loads(path.read_text())
                if intent.get('resolved') is not True:
                    unresolved_roles.add(intent['role_id'])
                    result = self.submit(path, intent)
                    if result:
                        created.append(result['id'])
            page = self.store.pool_candidates(self.volume.inventory_id, self.cursor)
            self.cursor = page['cursor']
            seen = set(unresolved_roles)
            for candidate in page['candidates']:
                if self.stopping():
                    break
                account = candidate['account']
                role_id = account['role_id']
                if role_id in seen:
                    continue
                seen.add(role_id)
                # Prepare/sign/simulate using an existing authorized key. These
                # bytes go only to simulation, never to broadcast or the queue.
                # Shared player/charge/object throttles and invalid requests do
                # not trigger growth. SQL rechecks availability, exact grants,
                # registration authority, pending requests and grant capacity.
                try:
                    self.signer.prepare(candidate)
                except (InvalidRequest, PreparationUnavailable, RpcError):
                    continue
                intent = {'role_id': role_id, 'source_account_id': account['id'],
                          'tx_id': candidate['transaction']['id'],
                          'permissions': str(uint(candidate['permissions'], 33554431)),
                          'max_accounts': self.maximum, 'request_id': str(uuid4()), 'resolved': False}
                intent['source_context'] = candidate['source_context']
                path = self.root / (str(role_id) + '.json')
                write_json(path, intent)
                result = self.submit(path, intent)
                if result:
                    created.append(result['id'])
        return created
