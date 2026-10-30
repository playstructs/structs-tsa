import tempfile
import unittest
from unittest.mock import Mock

from tsa.durable import Volume
from tsa.pools import Pools
from tsa.worker import PreparationUnavailable


class PoolTests(unittest.TestCase):
    def test_growth_copies_actual_grant_and_reuses_uuid_after_lost_acknowledgement(self):
        with tempfile.TemporaryDirectory() as root:
            store, signer = Mock(), Mock()
            candidate = {'transaction': {'id': 100}, 'account': {'id': 4, 'role_id': 2}, 'permissions': '512', 'source_context': {'player_id': '1-2', 'address': 'key', 'chain_id': 'structstestnet-111', 'created_at': '123'}}
            store.pool_candidates.return_value = {'cursor': 100, 'candidates': [candidate]}
            store.request_pool_account.side_effect = [ConnectionError('lost commit response'), {'id': 5}]
            volume = Volume(root)
            pool = Pools(store, Mock(), signer, volume)
            with self.assertRaises(ConnectionError):
                pool.run()
            request = store.request_pool_account.call_args.args[1].copy()
            self.assertEqual(request['permissions'], '512')
            self.assertEqual(request['max_accounts'], 40)
            reopened = Pools(store, Mock(), signer, Volume(root))
            self.assertEqual(reopened.run(), [5])
            retried = store.request_pool_account.call_args.args[1]
            self.assertEqual(retried['request_id'], request['request_id'])
            self.assertEqual(signer.prepare.call_count, 1)

    def test_shared_throttle_does_not_generate_keys(self):
        with tempfile.TemporaryDirectory() as root:
            store, signer = Mock(), Mock()
            store.pool_candidates.return_value = {'cursor': 1, 'candidates': [
                {'transaction': {'id': 1}, 'account': {'id': 4, 'role_id': 2}, 'permissions': '512', 'source_context': {'player_id': '1-2', 'address': 'key', 'chain_id': 'structstestnet-111', 'created_at': '123'}}]}
            signer.prepare.side_effect = PreparationUnavailable('Player throttle needs a later block')
            self.assertEqual(Pools(store, Mock(), signer, Volume(root)).run(), [])
            store.request_pool_account.assert_not_called()


if __name__ == '__main__':
    unittest.main()
