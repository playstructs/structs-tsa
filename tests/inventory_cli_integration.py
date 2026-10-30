"""Actual keyring formats and durable recovery, without network access."""
import tempfile
from pathlib import Path
from tsa.accounts import Keys
from tsa.durable import Volume
from tsa.signer import Cli
from tsa.worker import PreparationUnavailable

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

with tempfile.TemporaryDirectory() as root:
    volume = Path(root) / 'keys'
    volume.mkdir(mode=0o700)
    old_home = Path(root) / 'old-home'
    old_home.mkdir(mode=0o700)
    # Reproduce the old Dockerfile, rather than just its account_* names.
    (old_home / 'keyring-test').symlink_to(volume, target_is_directory=True)
    cli = Cli(home=root + '/new-home', keyring=str(volume))
    legacy = cli.run(['structsd', 'keys', 'add', 'account_flat_legacy', '--home', str(old_home),
                      '--keyring-backend', 'test', '--output', 'json'])['address']
    records = {file.name: file.read_bytes() for file in volume.iterdir() if file.suffix in ('.info', '.address')}
    assert len(records) == 2
    # The broken image may already have created this empty nested directory.
    (volume / 'keyring-test').mkdir(mode=0o700)
    keys = Keys(cli)
    assert keys.inventory() == [{'address': legacy, 'name': 'account_flat_legacy'}]
    request = {'request_id': 'ce601dd8-0d8e-44d8-b422-958d1c21a7fb', 'player_id': '1-1'}
    generated = keys.ensure(request)
    assert generated != legacy
    assert not list((volume / 'keyring-test').iterdir())
    restarted = Keys(Cli(home=root + '/restarted-home', keyring=str(volume)))
    assert {key['address'] for key in restarted.inventory()} == {legacy, generated}
    assert restarted.ensure(request) == generated
    proof = restarted.guild_proof(legacy, '0-1', 0)
    assert proof['address'] == legacy and proof['nonce'] == '0'
    assert all((volume / name).read_bytes() == contents for name, contents in records.items())
    # Never silently hide one populated layout behind another.
    cli.run(['structsd', 'keys', 'add', 'nested_conflict', '--home', root + '/unrelated-home',
             '--keyring-dir', str(volume), '--keyring-backend', 'test', '--output', 'json'])
    try:
        restarted.inventory()
        raise AssertionError('Mixed keyring layouts silently ignored existing keys')
    except PreparationUnavailable:
        pass
print('PASS: actual flat legacy volume, empty nested directory, in-place reuse and mixed-layout refusal')
