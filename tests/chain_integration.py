"""Actual v0.22 node and signer in a disposable --network none container."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from tsa.accounts import Keys
from tsa.rpc import Node, RpcError, tx_hash, uint
from tsa.signer import Cli, Lcd, Signer
from tsa.worker import PreparationUnavailable


def command(*args):
    result = subprocess.run(['structsd', *args], capture_output=True, timeout=45)
    if result.returncode:
        # Genesis commands do not carry or output recovery phrases here.
        raise RuntimeError(result.stderr.decode()[-4000:])
    return result


def main():
    if os.environ.get('TSA_DISPOSABLE_TEST') != 'network-none':
        raise RuntimeError('Only run in the documented network-disabled container')
    with tempfile.TemporaryDirectory(prefix='tsa-real-chain-') as root:
        home, keyring = root + '/chain', root + '/keys'
        cli = Cli(home=home, keyring=keyring)
        command('init', 'tsa-test', '--chain-id', 'structstestnet-111', '--home', home)
        key = cli.run(['structsd', 'keys', 'add', 'validator', *cli.flags()])
        address = key['address']
        del key
        genesis = Path(home, 'config/genesis.json')
        data = json.loads(genesis.read_text())
        data['app_state']['staking']['params']['bond_denom'] = 'ualpha'
        genesis.write_text(json.dumps(data))
        command('genesis', 'add-genesis-account', address, '1000000000000ualpha', '--home', home)
        command('genesis', 'gentx', 'validator', '1000000000ualpha', '--chain-id', 'structstestnet-111',
                '--home', home, '--keyring-dir', keyring, '--keyring-backend', 'test')
        command('genesis', 'collect-gentxs', '--home', home)
        data = json.loads(genesis.read_text())
        data['initial_height'] = '3353000'
        structs = data['app_state']['structs']
        structs['playerList'] = [{'id': '1-1', 'index': '1', 'creator': address, 'primaryAddress': address, 'name': 'Original'}]
        structs['addressList'] = [{'address': address, 'playerIndex': '1'}]
        structs['permissionList'] = [{'permissionId': '8-' + address + '@0', 'value': '33554431'}]
        genesis.write_text(json.dumps(data))
        command('genesis', 'validate', '--home', home)
        config = Path(home, 'config/config.toml')
        config.write_text(config.read_text().replace('timeout_commit = "5s"', 'timeout_commit = "3s"'))
        log = Path(root, 'node.log').open('w+')
        process = subprocess.Popen(['structsd', 'start', '--home', home, '--api.enable', '--api.address', 'tcp://127.0.0.1:1317',
            '--rpc.laddr', 'tcp://127.0.0.1:26657', '--minimum-gas-prices', '0.025ualpha'], stdout=log, stderr=log)
        try:
            node, lcd = Node('http://127.0.0.1:26657', 'structstestnet-111'), Lcd('http://127.0.0.1:1317')
            deadline = time.monotonic() + 90
            while True:
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read()[-6000:])
                try:
                    height = node.height()
                    break
                except RpcError:
                    if time.monotonic() > deadline:
                        log.seek(0)
                        raise RuntimeError(log.read()[-6000:])
                    time.sleep(.2)
            signer = Signer(node, lcd, cli, gas_price='0.025ualpha')
            claim = {'transaction': {'module': 'structs', 'command': 'player-update-name', 'args': ['1-1', 'TSA_Verified'],
                'flags': {}, 'contract': 'v022-1', 'chain_id': node.chain_id, 'prepared_height': str(height),
                'requested_player_id': '1-1'}, 'account': {'address': address}}
            def execute(claim):
                deadline = time.monotonic() + 45
                while True:
                    try:
                        signed = signer.prepare(claim)
                        saved = {'raw': signed.raw, 'tx_hash': tx_hash(signed.raw), 'source_height': str(signed.source_height),
                                 'account_number': str(signed.account_number), 'sequence': str(signed.sequence),
                                 'timeout_height': str(signed.timeout_height)}
                        signer.preflight(claim, saved)
                        break
                    except PreparationUnavailable:
                        if time.monotonic() > deadline:
                            raise
                admitted = node.broadcast(signed.raw)
                assert admitted['code'] == '0', admitted
                deadline = time.monotonic() + 30
                while True:
                    result = node.committed(saved)
                    if result is not None:
                        break
                    assert time.monotonic() < deadline, 'No isolated-chain inclusion'
                    time.sleep(.2)
                assert result['code'] == '0', result
                return admitted, result
            admitted, result = execute(claim)
            player = lcd.get('/structs/player/1-1', node.height())
            assert player['Player']['name'] == 'TSA_Verified', player
            keys = Keys(cli)
            request = {'request_id': '15d327b0-7765-44fe-bd9d-f014de0ab6ef', 'player_id': '1-1'}
            request['address'] = keys.ensure(request)
            current = lcd.get('/structs/address/' + request['address'], node.height())
            proof = keys.proof(request, node.chain_id, uint(current['proofNonce']))
            claim['transaction'].update(command='address-register', args=['1-1', request['address'],
                proof['pubkey'], proof['signature'], '33554431'])
            execute(claim)
            registered = lcd.get('/structs/address/' + request['address'], node.height())
            assert registered['playerId'] == '1-1' and uint(registered['permissions']) == 33554431, registered
            claim['account']['address'] = request['address']
            claim['transaction'].update(command='player-update-name', args=['1-1', 'TSA_Expanded'])
            execute(claim)
            assert lcd.get('/structs/player/1-1', node.height())['Player']['name'] == 'TSA_Expanded'
            print(json.dumps({'actual_release': '0.22.0', 'network': 'none', 'simulation': 'passed',
                'check_tx': admitted['code'], 'deliver_tx': result['code'], 'state_readback': True, 'address_registration_and_new_key_send': True, 'result': 'passed'}))
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            log.close()


if __name__ == '__main__':
    main()
