"""Explicit operator requests, with retry identities retained on the key volume."""
import getpass
import json
import sys
from uuid import UUID, uuid4

from .accounts import Keys
from .durable import Volume, private_directory, write_json
from .runtime import clients, report, reconcile
from .store import Store


def request(config, args):
    volume = Volume(config.keyring)
    request_id = str(UUID(args.request_id)) if args.request_id else str(uuid4())
    root = volume.root / 'operator-requests'
    private_directory(root)
    intent = {'request_id': request_id, 'command': args.command, 'permissions': str(args.permissions)}
    if args.command == 'request-role':
        intent.update(name=args.name, guild_id=args.guild_id)
    else:
        if not 1 <= args.maximum <= 40:
            raise ValueError('Role key maximum must be between 1 and 40')
        intent.update(role_id=args.role_id, max_accounts=args.maximum)
    path = root / (request_id + '.json')
    with volume.lock('operator-requests'):
        if path.exists() and json.loads(path.read_text()) != intent:
            raise ValueError('Request UUID already identifies different operator arguments')
        if not path.exists():
            write_json(path, intent)
    report('operator-request', request_id=request_id)
    store = Store(config.database)
    try:
        if args.command == 'request-role':
            result = store.scalar('SELECT signer.REQUEST_ROLE_V022(%s,%s,%s,%s::uuid)',
                (args.name, args.guild_id, args.permissions, request_id))
        else:
            result = store.scalar("SELECT signer.REQUEST_ACCOUNT_V022(%s,%s,%s,%s::uuid,'manual')",
                (args.role_id, args.permissions, args.maximum, request_id))
        report('operator-request-recorded', request_id=request_id, request=result)
    finally:
        store.close()


def import_key(config, args):
    if not 1 <= len(args.name) <= 256 or args.name.startswith('-') or '\0' in args.name:
        raise ValueError('Local key name must be a nonempty name, not a CLI option')
    _, _, cli, _ = clients(config)
    # Input is private stdin/TTY input, never an argument or environment value.
    mnemonic = getpass.getpass('Recovery phrase: ') if sys.stdin.isatty() else sys.stdin.buffer.read(4097).decode().strip()
    if not 1 <= len(mnemonic.encode()) <= 4096:
        raise ValueError('Recovery phrase input is missing or oversized')
    try:
        with Keys(cli).lock():
            key = cli.run([cli.binary, 'keys', 'add', args.name, '--recover', *cli.flags()], input=(mnemonic + '\n').encode())
    finally:
        mnemonic = None
    report('key-imported', address=key['address'])
    report('key-inventory', **reconcile(config))
