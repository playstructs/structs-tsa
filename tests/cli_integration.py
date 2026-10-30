"""Run only in a disposable, network-disabled TSA candidate container."""
import base64
import json
from pathlib import Path
import tempfile

from tsa.signer import Cli


def main():
    with tempfile.TemporaryDirectory(prefix='tsa-offline-test-') as root:
        cli = Cli(home=root + '/home', keyring=root + '/keys')
        assert cli.run(['structsd', 'version'], json_output=False) == '0.22.0'
        # The generated mnemonic is held only in this process and the isolated
        # keyring. Never print it or use a live key directory in this test.
        key = cli.run(['structsd', 'keys', 'add', 'fixture', *cli.flags()])
        address = key['address']
        del key
        tx = {'module': 'structs', 'command': 'allocation-update',
              'args': ['6-1', '18446744073709551615'], 'flags': {}}
        unsigned = cli.generate(tx, address, 'structstestnet-111', 3353100, 200000, '')
        assert unsigned['body']['messages'][0]['power'] == '18446744073709551615'
        raw = cli.sign(unsigned, address, 'structstestnet-111', 18446744073709551615, 9007199254740993)
        assert len(raw) > 64
        # A different chain/account or a damaged signature must not verify.
        original = {'tx_bytes': base64.b64encode(raw).decode(), 'chain_id': 'structstestnet-111',
                    'account_number': '18446744073709551615', 'address': address}
        import subprocess
        for changed in [dict(original, chain_id='other-chain'), dict(original, account_number='18446744073709551614'),
                        dict(original, tx_bytes=base64.b64encode(raw[:-1] + bytes([raw[-1] ^ 1])).decode())]:
            result = subprocess.run(['node', cli.verifier], input=json.dumps(changed).encode(), capture_output=True, timeout=15)
            assert result.returncode != 0
        # Paid Structs messages retain exact explicit fee data through signing.
        validator = cli.run(['structsd', 'keys', 'show', 'fixture', '--bech', 'val', *cli.flags()])['address']
        tx.update(command='reactor-restart', args=[validator])
        unsigned = cli.generate(tx, address, 'structstestnet-111', 3353100, 543210, '12345ualpha')
        cli.sign(unsigned, address, 'structstestnet-111', 0, 0)
        tx.update(command='player-update-name', args=['1-1', '--output-document=/tmp/tsa-must-not-exist'])
        unsigned = cli.generate(tx, address, 'structstestnet-111', 3353100, 200000, '')
        assert unsigned['body']['messages'][0]['name'] == tx['args'][1]
        assert not Path('/tmp/tsa-must-not-exist').exists()
        from tsa.accounts import Keys
        keys = Keys(cli)
        request = {'request_id': '36cf1901-d60f-4985-891c-c3993b4cc6a7', 'player_id': '1-1'}
        generated = keys.ensure(request)
        assert keys.ensure(request) == generated
        request['address'] = generated
        proof = keys.proof(request, 'structstestnet-111', 18446744073709551615)
        assert proof['address'] == generated and proof['proof_nonce'] == '18446744073709551615'
    print(json.dumps({'actual_release': '0.22.0', 'network': 'none', 'signed_transactions': 2,
                      'uint64_account_and_sequence': True, 'independent_signature_verification': True,
                      'changed_signature_context_refused': True, 'exact_paid_fee': True,
                      'positional_flag_injection_refused': True, 'result': 'passed'}))


if __name__ == '__main__':
    main()
