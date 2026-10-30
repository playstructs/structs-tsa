from copy import deepcopy
from decimal import Decimal
import json
import base64
import unittest
from unittest.mock import Mock

from tsa.rpc import RpcError
from tsa.signer import Cli, Signer
from tsa.worker import InvalidRequest, PreparationUnavailable


ADDRESS = 'structs1testkey'
CLAIM = {'transaction': {'id': 1, 'contract': 'v022-1', 'chain_id': 'structstestnet-111',
                        'requested_player_id': '1-1', 'prepared_height': 3353000,
                        'module': 'structs', 'command': 'allocation-update', 'args': ['6-1', '42'], 'flags': {}},
         'account': {'address': ADDRESS}}


class Node:
    chain_id = 'structstestnet-111'

    def __init__(self):
        self.heights = []
        self.simulation = {'code': 0, 'height': '3353000', 'value': base64.b64encode(
            json.dumps({'gas_info': {'gas_used': '1001'}}).encode()).decode()}

    def height(self):
        return self.heights.pop(0) if self.heights else 3353000

    def call(self, method, params):
        if method == 'abci_info':
            return {'response': {'version': '0.22.0'}}
        return {'response': self.simulation}


class Lcd:
    def __init__(self):
        self.owner = '1-1'
        self.account = {'@type': '/cosmos.auth.v1beta1.BaseAccount', 'address': ADDRESS,
                        'account_number': '18446744073709551615', 'sequence': '9007199254740993'}

    def get(self, path, height):
        if path.startswith('/structs/address/'):
            return {'address': ADDRESS, 'playerId': self.owner}
        return {'account': self.account}


class SignerTests(unittest.TestCase):
    def setUp(self):
        self.node = Node()
        self.lcd = Lcd()
        self.signer = Signer(self.node, self.lcd, Cli())

    def test_context_preserves_uint64_and_current_ownership(self):
        self.assertEqual(self.signer.context(CLAIM), (3353000, 18446744073709551615, 9007199254740993))
        self.lcd.owner = '1-2'
        with self.assertRaises(InvalidRequest):
            self.signer.context(CLAIM)

    def test_simulation_is_current_state_and_retries_when_chain_advances(self):
        self.assertEqual(self.signer.simulate(b'unsigned estimate', 3353000), 1001)
        self.node.heights = [3353000, 3353001]
        with self.assertRaises(PreparationUnavailable):
            self.signer.simulate(b'unsigned estimate', 3353000)

    def test_offline_signing_may_cross_blocks_but_not_account_sequences(self):
        cli = Mock()
        cli.generate.return_value = {'body': {'messages': [{'@type': '/structs.structs.MsgPlayerUpdateName'}]},
                                     'auth_info': {'fee': {'amount': [], 'gas_limit': '20000000'}}}
        cli.sign.return_value = b'independently verified signed bytes'
        signer = Signer(self.node, self.lcd, cli)
        signer.context = Mock(side_effect=[(3353000, 10, 20), (3353002, 10, 20)])
        signer.simulate = Mock(return_value=1000)
        signed = signer.prepare(CLAIM)
        self.assertEqual(signed.source_height, 3353002)
        self.assertEqual(signed.timeout_height, 3353100)
        signer.simulate.assert_called_once_with(cli.sign.return_value, 3353002)
        signer.context.side_effect = [(3353000, 10, 20), (3353002, 10, 21)]
        signer.simulate.reset_mock()
        with self.assertRaises(PreparationUnavailable):
            signer.prepare(CLAIM)
        signer.simulate.assert_not_called()

    def test_typed_chain_throttle_defers_but_permission_refusal_aborts_unsent(self):
        self.node.simulation = {'code': 2033, 'codespace': 'structs-ante', 'height': '0'}
        with self.assertRaises(PreparationUnavailable):
            self.signer.simulate(b'unsigned estimate', 3353000)
        self.node.simulation['code'] = 2011
        with self.assertRaisesRegex(InvalidRequest, 'structs-ante code 2011'):
            self.signer.simulate(b'unsigned estimate', 3353000)

    def test_prepared_sequence_change_and_expiry_are_unsent_failures(self):
        saved = {'account_number': '18446744073709551615', 'sequence': '9007199254740992',
                 'timeout_height': '0', 'raw': b'saved bytes'}
        with self.assertRaises(InvalidRequest):
            self.signer.preflight(CLAIM, saved)
        saved.update(sequence='9007199254740993', timeout_height='3353000')
        with self.assertRaises(InvalidRequest):
            self.signer.preflight(CLAIM, saved)

    def test_cli_uses_positional_separator_and_rejects_worker_flag_injection(self):
        cli = Cli()
        calls = []
        def generated(arguments):
            calls.append(arguments)
            return {'body': {'messages': [{'@type': '/structs.structs.MsgPlayerUpdateName', 'creator': ADDRESS}],
                             'timeout_height': '3353100'}}
        cli.run = generated
        tx = deepcopy(CLAIM['transaction'])
        tx['args'] = ['--output-document=/tmp/unwanted', 'name with spaces']
        cli.generate(tx, ADDRESS, 'structstestnet-111', 3353100, 1000, '')
        self.assertEqual(calls[0][-3:], ['--', *tx['args']])
        tx['flags'] = {'output-document': '/tmp/unwanted'}
        with self.assertRaises(InvalidRequest):
            cli.generate(tx, ADDRESS, 'structstestnet-111', 3353100, 1000, '')

    def test_price_requires_exact_native_units(self):
        self.assertEqual(Signer(self.node, self.lcd, Cli(), gas_price='0.025ualpha').gas_price, Decimal('0.025'))
        for price in ('1e3ualpha', '-1ualpha', '0.1alpha', 'NaNualpha'):
            with self.subTest(price=price), self.assertRaises(ValueError):
                Signer(self.node, self.lcd, Cli(), gas_price=price)


if __name__ == '__main__':
    unittest.main()
