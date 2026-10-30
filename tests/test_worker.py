import base64
from contextlib import contextmanager
from copy import deepcopy
import unittest

from tsa.rpc import Node, RpcError, RpcResponseError, tx_hash
from tsa.worker import InvalidRequest, PreparationUnavailable, Signed, Worker


RAW = b'opaque signed bytes for state-machine tests only'
CLAIM = {'transaction': {'id': 1, 'claim_token': 'test-claim'}, 'account': {'id': 2}}


class Store:
    def __init__(self):
        self.saved = None
        self.events = []
        self.begin_error = False
        self.result_error = False
        self.locked = False

    @contextmanager
    def lease(self, tx_id):
        yield not self.locked

    def claimed(self, tx_id):
        return CLAIM

    def submission(self, tx_id):
        return deepcopy(self.saved)

    def save(self, claim, signed):
        self.events.append('save-committed')
        assert self.saved is None
        self.saved = {'tx_id': 1, 'claim_token': 'test-claim', 'state': 'prepared',
                      'signed_bytes': '\\x' + signed.raw.hex(), 'tx_hash': tx_hash(signed.raw),
                      'account_number': str(signed.account_number), 'sequence': str(signed.sequence),
                      'source_height': str(signed.source_height), 'timeout_height': str(signed.timeout_height)}
        return deepcopy(self.saved)

    def begin(self, saved):
        assert self.saved['state'] == 'prepared'
        self.saved['state'] = 'sending'
        self.events.append('begin-committed')
        if self.begin_error:
            raise ConnectionError('Commit acknowledgement lost')
        return True

    def unknown(self, saved, reason):
        self.saved['state'] = 'unknown'

    def result(self, saved, result):
        if self.result_error:
            raise ConnectionError('Result commit unavailable')
        self.events.append('result-committed')
        self.saved['state'] = 'committed' if result['stage'] == 'deliver_tx' else ('accepted' if result['code'] == '0' else 'rejected')

    def abort(self, claim, reason):
        self.events.append('unsent-abort')


class Signer:
    def __init__(self):
        self.sign_count = 0
        self.preflight_error = None

    def prepare(self, claim):
        self.sign_count += 1
        return Signed(RAW, 18446744073709551615, 9007199254740993, 3353000, 0)

    def preflight(self, claim, saved):
        if self.preflight_error:
            raise self.preflight_error


class Transport:
    def __init__(self, store):
        self.store = store
        self.sends = []
        self.send_error = False
        self.included = False

    def broadcast(self, raw):
        assert self.store.events[-1] == 'begin-committed'
        self.sends.append(raw)
        if self.send_error:
            raise RpcError('response lost after node received bytes')
        return {'stage': 'check_tx', 'hash': tx_hash(raw), 'code': '0', 'codespace': '', 'log': ''}

    def committed(self, saved):
        if not self.included:
            return None
        return {'stage': 'deliver_tx', 'hash': tx_hash(saved['raw']), 'code': '0', 'codespace': '', 'log': '',
                'height': '3353001', 'index': '0', 'block_hash': 'A' * 64}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.signer = Signer()
        self.node = Transport(self.store)
        self.worker = Worker(self.store, self.node, self.signer)

    def test_save_and_marker_commit_before_send_and_inclusion_after_restart(self):
        self.assertEqual(self.worker.process(1), 'accepted')
        self.assertEqual(self.store.saved['sequence'], '9007199254740993')
        self.node.included = True
        self.assertEqual(self.worker.process(1), 'committed')
        self.assertEqual(self.node.sends, [RAW])
        self.assertEqual(self.signer.sign_count, 1)

    def test_transport_timeout_never_resigns_or_resends(self):
        self.node.send_error = True
        self.assertEqual(self.worker.process(1), 'unknown')
        self.assertEqual(self.worker.process(1), 'awaiting-inclusion')
        self.node.included = True
        self.assertEqual(self.worker.process(1), 'committed')
        self.assertEqual(self.node.sends, [RAW])
        self.assertEqual(self.signer.sign_count, 1)

    def test_ambiguous_begin_commit_does_not_send(self):
        self.store.begin_error = True
        with self.assertRaises(ConnectionError):
            self.worker.process(1)
        self.assertEqual(self.node.sends, [])
        self.assertEqual(self.worker.process(1), 'awaiting-inclusion')
        self.assertEqual(self.node.sends, [])

    def test_result_commit_failure_does_not_grant_second_send(self):
        self.store.result_error = True
        with self.assertRaises(ConnectionError):
            self.worker.process(1)
        self.store.result_error = False
        self.node.included = True
        self.assertEqual(self.worker.process(1), 'committed')
        self.assertEqual(self.node.sends, [RAW])

    def test_prepared_restart_reuses_bytes(self):
        self.signer.preflight_error = PreparationUnavailable()
        self.assertEqual(self.worker.process(1), 'preflight-unavailable')
        self.signer.preflight_error = None
        self.assertEqual(self.worker.process(1), 'accepted')
        self.assertEqual(self.signer.sign_count, 1)

    def test_definite_unsent_failure_can_abort_but_unknown_cannot(self):
        self.signer.preflight_error = InvalidRequest('invalid proof')
        self.assertEqual(self.worker.process(1), 'unsent-rejected')
        self.assertEqual(self.node.sends, [])
        self.store.saved['state'] = 'unknown'
        self.assertEqual(self.worker.process(1), 'awaiting-inclusion')
        self.assertEqual(self.store.events.count('unsent-abort'), 1)

    def test_other_worker_lease_is_not_claimed(self):
        self.store.locked = True
        self.assertEqual(self.worker.process(1), 'busy')
        self.assertEqual(self.signer.sign_count, 0)

    def test_tampered_saved_bytes_refuse_before_transport(self):
        self.signer.preflight_error = PreparationUnavailable()
        self.worker.process(1)
        self.store.saved['signed_bytes'] = '\\x00'
        with self.assertRaises(ValueError):
            self.worker.process(1)
        self.assertEqual(self.node.sends, [])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        encoded = base64.b64encode(RAW).decode()
        self.result = {'code': 0, 'codespace': '', 'log': ''}
        self.responses = {
            'tx': {'hash': tx_hash(RAW), 'height': '3353001', 'index': 0, 'tx': encoded, 'tx_result': self.result},
            'block': {'block_id': {'hash': 'A' * 64}, 'block': {
                'header': {'chain_id': 'structstestnet-111', 'height': '3353001'}, 'data': {'txs': [encoded]}}},
            'block_results': {'height': '3353001', 'txs_results': [self.result]},
        }
        self.node = Node('http://localhost:26657', 'structstestnet-111')
        self.node.call = lambda method, params, **kwargs: deepcopy(self.responses[method])
        self.saved = {'raw': RAW, 'tx_hash': tx_hash(RAW), 'source_height': '3353000'}

    def test_same_chain_bytes_height_index_and_code_are_required(self):
        self.assertEqual(self.node.committed(self.saved)['stage'], 'deliver_tx')
        modifications = [
            ('tx', lambda r: r.update(index=1)),
            ('tx', lambda r: r.update(hash='B' * 64)),
            ('tx', lambda r: r.update(tx=base64.b64encode(b'different').decode())),
            ('block', lambda r: r['block']['header'].update(chain_id='wrong-chain')),
            ('block', lambda r: r['block']['header'].update(height='3353002')),
            ('block', lambda r: r['block']['data'].update(txs=[])),
            ('block_results', lambda r: r.update(height='3353002')),
            ('block_results', lambda r: r.update(txs_results=[{'code': 5}])),
        ]
        for name, change in modifications:
            with self.subTest(name=name):
                original = deepcopy(self.responses[name])
                change(self.responses[name])
                with self.assertRaises(RpcError):
                    self.node.committed(self.saved)
                self.responses[name] = original

    def test_missing_index_entry_keeps_transaction_unresolved(self):
        def missing(*args, **kwargs):
            raise RpcResponseError({'code': -32603, 'data': 'tx (' + tx_hash(RAW) + ') not found'})
        self.node.call = missing
        self.assertIsNone(self.node.committed(self.saved))


if __name__ == '__main__':
    unittest.main()
