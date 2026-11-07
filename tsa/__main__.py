import argparse
import json
from pathlib import Path
import sys
import time

from .health import health_reason
from .config import Config
from .runtime import Runtime, reconcile, report


def main():
    parser = argparse.ArgumentParser(description='Structs v0.22 transaction signing authority')
    commands = parser.add_subparsers(dest='command')
    for name in ('run', 'reconcile', 'health'):
        commands.add_parser(name)
    key = commands.add_parser('request-key')
    key.add_argument('--role-id', required=True, type=int)
    key.add_argument('--permissions', required=True, type=int)
    key.add_argument('--maximum', type=int, default=40)
    key.add_argument('--request-id')
    role = commands.add_parser('request-role')
    role.add_argument('--name', required=True)
    role.add_argument('--guild-id', required=True)
    role.add_argument('--permissions', required=True, type=int)
    role.add_argument('--request-id')
    imported = commands.add_parser('import-key')
    imported.add_argument('--name', required=True)
    args = parser.parse_args()
    if args.command == 'health':
        status = json.loads(Path('/run/tsa/health.json').read_text())
        reason = health_reason(status, time.time())
        if reason:
            report('unhealthy', reason=reason)
        return 1 if reason else 0
    config = Config.from_environment()
    if args.command == 'reconcile':
        report('key-inventory', **reconcile(config))
    elif args.command in ('request-key', 'request-role'):
        from .operator import request
        request(config, args)
    elif args.command == 'import-key':
        from .operator import import_key
        import_key(config, args)
    else:
        Runtime(config).run()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        report('startup-failed', error=type(error).__name__)
        sys.exit(1)
