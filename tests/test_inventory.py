import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tsa.durable import Journal, Volume
from tsa.inventory import Inventory
from tsa.rpc import tx_hash


class RecoveryTests(unittest.TestCase):
    def test_each_key_observes_a_fresh_height_during_a_long_inventory_pass(self):
        store, node, lcd, keys, journal = Mock(), Mock(), Mock(), Mock(), Mock()
        keys.inventory.return_value = [{'name': 'a', 'address': 'a'}, {'name': 'b', 'address': 'b'}]
        def context(height):
            return {'transaction_ready': True, 'protocol': 'v0.22.0',
                    'chain_id': 'structstestnet-111', 'indexed_height': str(height)}
        store.readiness.side_effect = [context(3353000), context(3353000), context(3353008)]
        node.chain_id = 'structstestnet-111'
        node.height.side_effect = [3353001, 3353009]
        node.call.return_value = {'response': {'version': '0.22.0'}}
        lcd.get.side_effect = lambda path, height: {'address': path.rsplit('/', 1)[1], 'playerId': '1-1', 'permissions': '16'}
        journal.observe.return_value = set()
        store.reconcile_key.return_value = 'ready'
        inventory = Inventory(store, node, lcd, keys, Mock(inventory_id='volume'), journal)
        self.assertEqual(inventory.run(), {'known': 2, 'ready': 2})
        self.assertEqual([call.args[3:5] for call in store.reconcile_key.call_args_list],
                         [(3353000, 3353001), (3353008, 3353009)])

    def test_volume_identity_and_pending_send_survive_database_loss(self):
        with tempfile.TemporaryDirectory() as root:
            first = Volume(root)
            journal = Journal(first)
            raw = b'a transaction already prepared by SQL'
            saved = {'tx_id': 42, 'claim_token': '00000000-0000-0000-0000-000000000001',
                     'tx_hash': tx_hash(raw), 'raw': raw, 'signed_bytes': '\\x' + raw.hex(),
                     'account_number': '18446744073709551615', 'sequence': '9007199254740993',
                     'source_height': '3353000', 'timeout_height': '3353100'}
            claim = {'transaction': {'chain_id': 'structstestnet-111'}, 'account': {'address': 'surviving-key'}}
            journal.begin(claim, saved)
            reopened = Journal(Volume(root))
            self.assertEqual(first.inventory_id, reopened.volume.inventory_id)
            node = Mock(chain_id='structstestnet-111')
            node.committed.return_value = None
            self.assertEqual(reopened.observe(node), {'surviving-key'})
            reopened.begin(claim, saved)  # Same immutable marker, no duplicate.
            self.assertEqual(len(reopened.unresolved()), 1)
            with self.assertRaises(ValueError):
                reopened.begin(dict(claim, account={'address': 'another-key'}), saved)
            node.committed.return_value = {'stage': 'deliver_tx', 'hash': saved['tx_hash'], 'code': '0'}
            self.assertEqual(reopened.observe(node), set())
            with self.assertRaises(ValueError):
                reopened.begin(claim, saved)

    def test_one_resolved_send_does_not_release_another_on_the_same_address(self):
        with tempfile.TemporaryDirectory() as root:
            journal = Journal(Volume(root))
            claim = {'transaction': {'chain_id': 'structstestnet-111'}, 'account': {'address': 'same-key'}}
            for index in (1, 2):
                raw = str(index).encode()
                journal.begin(claim, {'tx_id': index, 'claim_token': '00000000-0000-0000-0000-000000000001',
                    'tx_hash': tx_hash(raw), 'raw': raw, 'signed_bytes': '\\x' + raw.hex(),
                    'account_number': '1', 'sequence': str(index), 'source_height': '3353000', 'timeout_height': '3353100'})
            node = Mock(chain_id='structstestnet-111')
            node.committed.side_effect = lambda saved: ({'stage': 'deliver_tx', 'hash': saved['tx_hash'], 'code': '0'}
                                                      if saved['tx_id'] == 1 else None)
            self.assertEqual(journal.observe(node), {'same-key'})
            self.assertEqual(len(journal.unresolved()), 1)

    def test_malformed_journal_never_silently_frees_keys(self):
        with tempfile.TemporaryDirectory() as root:
            journal = Journal(Volume(root))
            (journal.pending / 'bad.json').write_text('{}')
            with self.assertRaises(ValueError):
                journal.unresolved()

    def test_inventory_records_keys_even_before_chain_index_is_ready(self):
        store, node, lcd, keys = Mock(), Mock(), Mock(), Mock()
        keys.inventory.return_value = [{'name': 'legacy or new name', 'address': 'key'}]
        store.readiness.return_value = {'transaction_ready': False}
        journal = Mock()
        journal.observe.return_value = set()
        inventory = Inventory(store, node, lcd, keys, Mock(inventory_id='volume'), journal)
        self.assertEqual(inventory.run(), {'known': 1, 'waiting-index': 1})
        store.sync_keys.assert_called_once_with('volume', keys.inventory.return_value)
        store.reconcile_key.assert_not_called()

    def test_reload_checks_indexed_and_latest_ownership_and_holds_uncertain_sends(self):
        store, node, lcd, keys, journal = Mock(), Mock(), Mock(), Mock(), Mock()
        keys.inventory.return_value = [{'name': 'key', 'address': 'address'}]
        store.readiness.return_value = {'transaction_ready': True, 'protocol': 'v0.22.0',
                                       'chain_id': 'structstestnet-111', 'indexed_height': '3353000'}
        node.chain_id = 'structstestnet-111'
        node.height.return_value = 3353001
        node.call.return_value = {'response': {'version': '0.22.0'}}
        owner = {'address': 'address', 'playerId': '1-1', 'permissions': '16'}
        lcd.get.return_value = owner
        journal.observe.return_value = {'address'}
        store.reconcile_key.return_value = 'held'
        inventory = Inventory(store, node, lcd, keys, Mock(inventory_id='volume'), journal)
        self.assertEqual(inventory.run(), {'known': 1, 'held': 1})
        store.reconcile_key.assert_called_once_with('volume', 'address', 'structstestnet-111', 3353000, 3353001, '1-1', 16, True)
        store.reconcile_key.reset_mock()
        lcd.get.side_effect = [owner, dict(owner, playerId='1-2')]
        self.assertEqual(inventory.run(), {'known': 1, 'unverified': 1})
        store.reconcile_key.assert_not_called()
        store.invalidate_key.assert_called_once_with('volume', 'address')


if __name__ == '__main__':
    unittest.main()
