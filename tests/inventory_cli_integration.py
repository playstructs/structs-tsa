"""Actual keyring formats and durable recovery, without network access."""
import tempfile
from tsa.accounts import Keys
from tsa.durable import Volume
from tsa.signer import Cli

with tempfile.TemporaryDirectory() as root:
    cli = Cli(home=root + '/home', keyring=root + '/keys')
    keys = Keys(cli)
    legacy = cli.run(['structsd', 'keys', 'add', 'account_legacy', *cli.flags()])['address']
    request = {'request_id': 'cbb8449d-d4b8-47a4-888e-c2c355d2ca21', 'player_id': '1-1'}
    current = keys.ensure(request)
    inventory = keys.inventory()
    assert {key['address'] for key in inventory} == {legacy, current}
    proof = keys.guild_proof(legacy, '0-1', 0)
    assert proof['address'] == legacy and proof['nonce'] == '0'
    identity = Volume(cli.keyring).inventory_id
    assert Volume(cli.keyring).inventory_id == identity
    assert keys.ensure(request) == current
print('PASS: actual legacy and new keyring names, stable inventory, restart-safe key reuse')
