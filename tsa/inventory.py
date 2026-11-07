"""Reconcile public key identities automatically without changing any grant."""
from urllib.parse import quote

from .rpc import RpcError, uint
from .worker import PreparationUnavailable


class NodeProtocolUnavailable(PreparationUnavailable):
    """The selected node has not reached the supported signing protocol."""


class Inventory:
    def __init__(self, store, node, lcd, keys, volume, journal, stopping=lambda: False):
        self.store, self.node, self.lcd, self.keys = store, node, lcd, keys
        self.volume, self.journal = volume, journal
        self.stopping = stopping

    def run(self):
        keys = self.keys.inventory()
        self.store.sync_keys(self.volume.inventory_id, keys)
        # Public identities are known to SQL even before its index or RPC is
        # ready. Registration/generation is never inferred from a key name.
        held = self.journal.observe(self.node, self.store)
        context = self.store.readiness()
        if not context or context.get('transaction_ready') is not True or context.get('protocol') != 'v0.22.0':
            return {'known': len(keys), 'waiting-index': len(keys)}
        if self.node.call('abci_info', {}).get('response', {}).get('version') not in ('0.22.0', 'v0.22.0'):
            raise NodeProtocolUnavailable('Key activation requires the verified v0.22.0 protocol')
        counts = {'known': len(keys)}
        for key in keys:
            if self.stopping():
                break
            address = key['address']
            try:
                # A large inventory can span blocks. Observe each key against
                # a fresh snapshot instead of aging the first key's context.
                context = self.store.readiness()
                if not context or context.get('transaction_ready') is not True or context.get('protocol') != 'v0.22.0':
                    raise PreparationUnavailable('Local key recovery requires a ready index')
                height = uint(context['indexed_height'])
                tip = self.node.height()
                if context.get('chain_id') != self.node.chain_id or not height <= tip <= height + 5:
                    raise PreparationUnavailable('Local key recovery requires a current matching index')
                path = '/structs/address/' + quote(address, safe='')
                indexed = self.lcd.get(path, height)
                current = self.lcd.get(path, tip) if tip != height else indexed
                fields = ('address', 'playerId', 'permissions')
                if indexed.get('address') != address or any(indexed.get(name) != current.get(name) for name in fields):
                    raise PreparationUnavailable('Key ownership changed since the indexed snapshot')
                permissions = uint(current.get('permissions'), 33554431)
                state = self.store.reconcile_key(self.volume.inventory_id, address, self.node.chain_id,
                    height, tip, current['playerId'], permissions, address in held)
            except (RpcError, PreparationUnavailable, KeyError):
                state = 'unverified'
                self.store.invalidate_key(self.volume.inventory_id, address)
            counts[state] = counts.get(state, 0) + 1
        return counts
