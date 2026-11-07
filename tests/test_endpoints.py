from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest
from unittest.mock import Mock

from tsa.config import Config
from tsa.endpoints import EndpointSelector, EndpointsUnavailable
from tsa.rpc import RpcError
from tsa.worker import PreparationUnavailable, Worker
from test_worker import Store, Signer, Transport, RAW


CHAIN = 'structstestnet-111'
HEIGHT = 3480000
CONTEXT = dict(transaction_ready=True, protocol='v0.22.0', chain_id=CHAIN, indexed_height=str(HEIGHT))
CONFIG = Config('unused', CHAIN, 'http://local.test:26657', 'http://local.test:1317',
                '/unused', '/unused', 6, 40, None, 'https://public.test:26657', 'https://public.test')


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.selector = EndpointSelector(CONFIG, lambda: self.now, lambda: self.now)
        for pair in [self.selector.primary, self.selector.fallback]:
            pair.node.call = Mock(side_effect=lambda method, params: {
                'status': {'node_info': {'network': CHAIN}, 'sync_info': {'catching_up': False, 'latest_block_height': str(HEIGHT)}},
                'abci_info': {'response': {'version': '0.22.0'}},
            }[method])
            pair.lcd.get = Mock(return_value={'default_node_info': {'network': CHAIN}, 'application_version': {'version': '0.22.0'}})

    def select(self):
        return self.selector.select(CONTEXT)

    def advance(self):
        self.now += 10

    def fail_primary(self):
        self.selector.primary.node.call.side_effect = RpcError('unavailable')

    def test_prefers_primary_and_probes_paired_lcd_at_rpc_height(self):
        pair = self.select()
        self.assertIs(pair, self.selector.primary)
        pair.lcd.get.assert_called_once_with('/cosmos/base/tendermint/v1beta1/node_info', HEIGHT)
        self.selector.fallback.node.call.assert_not_called()
        self.select()
        self.assertEqual(pair.node.call.call_count, 2)

    def test_old_catching_up_wrong_chain_and_lagging_primary_use_fallback(self):
        for change in ['old-version', 'catching-up', 'wrong-chain', 'behind-index', 'ahead-index', 'malformed']:
            with self.subTest(change=change):
                self.setUp()
                original = self.selector.primary.node.call.side_effect
                def call(method, params):
                    result = original(method, params)
                    if method == 'abci_info' and change == 'old-version':
                        result['response']['version'] = '0.21.0'
                    if method == 'status':
                        if change == 'catching-up': result['sync_info']['catching_up'] = True
                        if change == 'wrong-chain': result['node_info']['network'] = 'wrong'
                        if change == 'behind-index': result['sync_info']['latest_block_height'] = str(HEIGHT-1)
                        if change == 'ahead-index': result['sync_info']['latest_block_height'] = str(HEIGHT+6)
                        if change == 'malformed': result['node_info'] = None
                    return result
                self.selector.primary.node.call.side_effect = call
                self.assertIs(self.select(), self.selector.fallback)

    def test_lcd_failure_or_wrong_identity_never_mixes_pairs(self):
        for value in [None, {'default_node_info': {'network': 'wrong'}},
                      {'default_node_info': {'network': CHAIN}, 'application_version': {'version': '0.21.0'}}]:
            with self.subTest(value=value):
                self.setUp()
                self.selector.primary.lcd.get.return_value = value
                pair = self.select()
                self.assertIs(pair.node, self.selector.fallback.node)
                self.assertIs(pair.lcd, self.selector.fallback.lcd)
        self.setUp()
        self.selector.primary.lcd.get.side_effect = PreparationUnavailable('height missing')
        self.assertIs(self.select(), self.selector.fallback)

    def test_both_unavailable_fail_closed_and_status_contains_only_fixed_codes(self):
        self.fail_primary()
        self.selector.fallback.lcd.get.side_effect = PreparationUnavailable('secret URL or body')
        with self.assertRaises(EndpointsUnavailable): self.select()
        self.assertEqual(self.selector.snapshot(), {'mode': 'unavailable', 'checked_at': 1000,
                         'failures': {'primary': 'rpc-unavailable', 'fallback': 'lcd-unavailable'}})
        with self.assertRaises(EndpointsUnavailable): self.select()
        self.assertEqual(self.selector.primary.node.call.call_count, 1)

    def test_recovery_requires_three_spaced_successes_and_resets_on_failure(self):
        healthy = self.selector.primary.node.call.side_effect
        self.fail_primary()
        pinned = self.select()
        self.selector.primary.node.call.side_effect = healthy
        for _ in range(2):
            self.advance()
            self.assertIs(self.select(), self.selector.fallback)
            for _ in range(5): self.assertIs(self.select(), self.selector.fallback)
        self.fail_primary()
        self.advance()
        self.assertIs(self.select(), self.selector.fallback)
        self.selector.primary.node.call.side_effect = healthy
        for _ in range(2):
            self.advance()
            self.assertIs(self.select(), self.selector.fallback)
        self.advance()
        self.assertIs(self.select(), self.selector.primary)
        self.assertIs(pinned.node, self.selector.fallback.node)
        self.assertIs(pinned.lcd, self.selector.fallback.lcd)

    def test_fallback_loss_does_not_bypass_primary_recovery_threshold(self):
        healthy = self.selector.primary.node.call.side_effect
        self.fail_primary()
        self.select()
        self.selector.primary.node.call.side_effect = healthy
        self.selector.fallback.node.call.side_effect = RpcError('offline')
        for _ in range(2):
            self.advance()
            with self.assertRaises(EndpointsUnavailable): self.select()
        self.advance()
        self.assertIs(self.select(), self.selector.primary)

    def test_read_only_recovery_can_select_node_while_index_not_ready(self):
        self.assertIs(self.selector.select(dict(transaction_ready=False)), self.selector.primary)

    def test_concurrent_workers_share_one_probe_and_same_concrete_pair(self):
        self.fail_primary()
        with ThreadPoolExecutor(max_workers=12) as workers:
            pairs = list(workers.map(lambda _: self.select(), range(24)))
        self.assertTrue(all(pair is self.selector.fallback for pair in pairs))
        self.assertEqual(self.selector.primary.node.call.call_count, 1)
        self.assertEqual(self.selector.fallback.node.call.call_count, 2)
        self.selector.fallback.lcd.get.assert_called_once()

    def test_wrong_index_contract_rejects_both_pairs(self):
        with self.assertRaises(EndpointsUnavailable):
            self.selector.select(dict(CONTEXT, chain_id='wrong-chain'))
        self.assertEqual(self.selector.snapshot()['failures'],
                         {'primary': 'index-contract-mismatch', 'fallback': 'index-contract-mismatch'})

    def test_disabled_fallback_and_credential_urls(self):
        selector = EndpointSelector(replace(CONFIG, rpc_fallback=None, lcd_fallback=None))
        selector.primary.node.call = Mock(side_effect=RpcError('offline'))
        with self.assertRaises(EndpointsUnavailable): selector.select(CONTEXT)
        for settings in [dict(rpc_fallback='https://user:password@public.test'), dict(lcd_fallback='https://user:password@public.test'),
                         dict(lcd_fallback=None)]:
            with self.assertRaises(ValueError): EndpointSelector(replace(CONFIG, **settings))

    def test_uncertain_broadcast_recovers_on_new_pair_without_resigning_or_resending(self):
        store, signer = Store(), Signer()
        local, public = Transport(store), Transport(store)
        self.selector.primary.node.broadcast = local.broadcast
        self.selector.primary.node.committed = local.committed
        self.selector.fallback.node.broadcast = public.broadcast
        self.selector.fallback.node.committed = public.committed
        local.send_error = True
        pair = self.select()
        self.assertEqual(Worker(store, pair.node, signer).process(1), 'unknown')
        self.fail_primary()
        self.advance()
        pair = self.select()
        self.assertEqual(Worker(store, pair.node, signer).process(1), 'awaiting-inclusion')
        public.included = True
        self.assertEqual(Worker(store, pair.node, signer).process(1), 'committed')
        self.assertEqual(local.sends, [RAW])
        self.assertEqual(public.sends, [])
        self.assertEqual(signer.sign_count, 1)


class HttpPairTests(unittest.TestCase):
    def test_real_transports_reject_unpinned_lcd_then_select_valid_fallback(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def reply(self, value, height=None):
                self.send_response(200)
                if height: self.send_header('x-cosmos-block-height', height)
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                result = {'node_info': {'network': CHAIN}, 'sync_info': {'catching_up': False, 'latest_block_height': str(HEIGHT)}} \
                    if request['method'] == 'status' else {'response': {'version': '0.22.0'}}
                self.reply({'jsonrpc': '2.0', 'id': request['id'], 'result': result})
            def do_GET(self):
                self.reply({'default_node_info': {'network': CHAIN}, 'application_version': {'version': '0.22.0'}},
                           self.headers.get('x-cosmos-block-height') if self.path.startswith('/fallback/') else None)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            url = 'http://127.0.0.1:' + str(server.server_port)
            selector = EndpointSelector(replace(CONFIG, rpc=url, lcd=url, rpc_fallback=url, lcd_fallback=url+'/fallback'))
            self.assertEqual(selector.select(CONTEXT).mode, 'fallback')
            self.assertEqual(selector.snapshot()['failures']['primary'], 'lcd-unavailable')
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
