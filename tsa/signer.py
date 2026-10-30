"""Pinned CLI signing with exact account state and independent byte verification."""
import base64
from decimal import Decimal, ROUND_CEILING, localcontext
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

from .rpc import NoRedirect, RpcError, decode_bytes, uint
from .worker import InvalidRequest, PreparationUnavailable, Signed


class Lcd:
    def __init__(self, url, timeout=10):
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('LCD URL must be an HTTP(S) endpoint without embedded credentials')
        self.url = url.rstrip('/')
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect())

    def get(self, path, height):
        request = urllib.request.Request(self.url + path, headers={'x-cosmos-block-height': str(height)})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                heights = []
                for name in ('x-cosmos-block-height', 'grpc-metadata-x-cosmos-block-height'):
                    heights.extend(response.headers.get_all(name, []))
                if not heights or any(value != str(height) for value in heights):
                    raise PreparationUnavailable('LCD did not prove the requested state height')
                body = response.read(1048577)
            if len(body) > 1048576:
                raise PreparationUnavailable('LCD response exceeds limit')
            return json.loads(body)
        except (OSError, ValueError, urllib.error.URLError) as error:
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            raise PreparationUnavailable('Height-pinned chain state is unavailable') from error


class Cli:
    def __init__(self, binary='structsd', home='/var/structs/chain', keyring='/var/structs/accounts',
                 verifier='/opt/structs-sign-proxy/verify-tx.mjs'):
        self.binary = binary
        self.home = home
        self.keyring = keyring
        self.verifier = verifier

    def run(self, arguments, input=None, json_output=True):
        environment = {key: value for key, value in os.environ.items() if key != 'DATABASE_URL'}
        try:
            result = subprocess.run(arguments, input=input, capture_output=True, timeout=30, env=environment)
            if result.returncode or len(result.stdout) > 2 * 1048576:
                raise PreparationUnavailable('Signing command failed; inspect configuration and key availability')
            return json.loads(result.stdout) if json_output else result.stdout.decode().strip()
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            raise PreparationUnavailable('Signing command unavailable') from error

    def flags(self):
        return ['--home', self.home, '--keyring-dir', self.keyring, '--keyring-backend', 'test', '--output', 'json']

    def generate(self, tx, address, chain_id, timeout_height, gas, fees, account_number=0, sequence=0):
        # The current v022 SQL wrappers emit only direct Structs messages. Do
        # not let a queue row select a CLI subcommand that can broadcast or read
        # files. Business flags are a reviewed allowlist, not an exclusion list.
        allowed = {'owner-id', 'delegator-address', 'guild-id', 'player-id', 'substation-id', 'allocation-type', 'controller',
                   'player-name', 'player-pfp', 'player-pfp-client-render-attributes'}
        if tx.get('module') != 'structs' or not re.fullmatch('[a-z][a-z0-9-]*', tx.get('command', '')):
            raise InvalidRequest('Unsupported v022 transaction command')
        args, flags = tx.get('args'), tx.get('flags')
        if not isinstance(args, list) or len(args) > 64 or any(not isinstance(item, str) or '\0' in item for item in args):
            raise InvalidRequest('Transaction arguments must be exact strings')
        if not isinstance(flags, dict) or not set(flags) <= allowed or any(not isinstance(value, str) or '\0' in value for value in flags.values()):
            raise InvalidRequest('Transaction includes unsupported command flags')
        if len(json.dumps([args, flags]).encode()) > 1048576:
            raise InvalidRequest('Transaction arguments exceed the worker size limit')
        command = [self.binary, 'tx', tx['module'], tx['command'], *self.flags(), '--generate-only', '--offline',
                   '--from', address, '--chain-id', '', '--gas', str(gas), '--fees', fees,
                   '--timeout-height', str(timeout_height), '--account-number', str(account_number), '--sequence', str(sequence)]
        command.extend('--' + name + '=' + value for name, value in sorted(flags.items()))
        # Even strings beginning with '-' remain positional data, never flags.
        unsigned = self.run(command + ['--', *args])
        body = unsigned.get('body', {})
        messages = body.get('messages')
        if not isinstance(messages, list) or len(messages) != 1 or messages[0].get('creator') != address:
            raise InvalidRequest('Generated message does not have the claimed single signer')
        if not messages[0].get('@type', '').startswith('/structs.structs.Msg') or messages[0]['@type'] == '/structs.structs.MsgUpdateParams':
            raise InvalidRequest('Generated message is outside the v022 signing contract')
        if body.get('unordered') or body.get('timeout_timestamp') not in (None, '0', '0001-01-01T00:00:00Z') \
                or uint(body.get('timeout_height')) != timeout_height or body.get('memo', '') or body.get('extension_options') or body.get('non_critical_extension_options'):
            raise InvalidRequest('Generated transaction has unexpected body options')
        return unsigned

    def sign(self, unsigned, address, chain_id, account_number, sequence):
        with tempfile.TemporaryDirectory(prefix='structs-tsa-sign-') as directory:
            path = Path(directory) / 'unsigned.json'
            path.write_text(json.dumps(unsigned))
            signed = self.run([self.binary, 'tx', 'sign', str(path), *self.flags(), '--offline', '--sign-mode', 'direct',
                               '--from', address, '--chain-id', chain_id,
                               '--account-number', str(account_number), '--sequence', str(sequence)])
            if signed.get('body') != unsigned.get('body') or signed.get('auth_info', {}).get('fee') != unsigned.get('auth_info', {}).get('fee'):
                raise InvalidRequest('CLI changed the prepared body or fee while signing')
            if signed.get('auth_info', {}).get('tip') is not None:
                raise InvalidRequest('Unexpected transaction tip')
            signed_path = Path(directory) / 'signed.json'
            signed_path.write_text(json.dumps(signed))
            raw = decode_bytes(self.run([self.binary, 'tx', 'encode', str(signed_path), '--home', self.home], json_output=False))
            if not 1 <= len(raw) <= 1048576:
                raise InvalidRequest('Signed transaction exceeds size limit')
            verified = self.run(['node', self.verifier], input=json.dumps({
                'tx_bytes': base64.b64encode(raw).decode(), 'chain_id': chain_id,
                'account_number': str(account_number), 'address': address}).encode())
            if verified != {'valid': True, 'sequence': str(sequence), 'address': address}:
                raise InvalidRequest('Signed transaction failed independent verification')
            return raw


class Signer:
    def __init__(self, node, lcd, cli, gas_price=None, timeout_blocks=100, max_gas=20000000):
        self.node, self.lcd, self.cli = node, lcd, cli
        self.timeout_blocks, self.max_gas = timeout_blocks, max_gas
        if gas_price is not None and not re.fullmatch(r'(0|[1-9][0-9]{0,19})(\.[0-9]{1,18})?ualpha', gas_price):
            raise ValueError('Gas price must be an exact nonnegative ualpha price')
        self.gas_price = Decimal(gas_price[:-6]) if gas_price is not None else None

    def context(self, claim):
        tx, account = claim['transaction'], claim['account']
        if tx.get('contract') != 'v022-1' or tx.get('chain_id') != self.node.chain_id:
            raise InvalidRequest('Request has the wrong chain or protocol contract')
        height = self.node.height()
        if height < uint(tx['prepared_height']):
            raise PreparationUnavailable('Chain node is behind the queued request')
        version = self.node.call('abci_info', {}).get('response', {}).get('version')
        if version not in ('0.22.0', 'v0.22.0'):
            raise PreparationUnavailable('Chain application is outside the verified v0.22.0 protocol')
        address = account['address']
        path = quote(address, safe='')
        owner = self.lcd.get('/structs/address/' + path, height)
        if owner.get('address') != address or owner.get('playerId') != tx.get('requested_player_id'):
            raise InvalidRequest('Signing address no longer belongs to the requested player')
        auth = self.lcd.get('/cosmos/auth/v1beta1/accounts/' + path, height).get('account', {})
        # Managed TSA keys are ordinary accounts. Nested vesting/module accounts
        # require their own signer contract, not a guessed account-number path.
        if auth.get('@type') != '/cosmos.auth.v1beta1.BaseAccount' or auth.get('address') != address:
            raise PreparationUnavailable('Signing account is not an ordinary chain account')
        return height, uint(auth.get('account_number')), uint(auth.get('sequence'))

    def simulate(self, raw, height):
        # SDK v0.53's Simulate uses current app state even if a query supplies
        # a historical height. Bracket it with the same current height rather
        # than misrepresenting a response header as historical simulation.
        if self.node.height() != height:
            raise PreparationUnavailable('Chain advanced during transaction preparation')
        response = self.node.call('abci_query', {'path': '/app/simulate', 'data': raw.hex().upper(),
                                               'height': str(height), 'prove': False}).get('response', {})
        if self.node.height() != height:
            raise PreparationUnavailable('Chain advanced during transaction simulation')
        code = uint(response.get('code'), (1 << 32) - 1)
        if code:
            codespace = response.get('codespace')
            if codespace == 'structs-ante' and code in (2021, 2022, 2031, 2033, 2040, 2041, 2043):
                raise PreparationUnavailable('Chain throttle requires a later block')
            if not isinstance(codespace, str) or len(codespace) > 128:
                raise RpcError('Malformed simulation result')
            raise InvalidRequest('Unsent simulation rejected by ' + codespace + ' code ' + str(code))
        if uint(response.get('height')) != height:
            raise PreparationUnavailable('Simulation response has an unexpected query height')
        try:
            info = json.loads(decode_bytes(response.get('value')))
            return uint(info['gas_info']['gas_used'])
        except (KeyError, ValueError, TypeError) as error:
            raise RpcError('Malformed simulation gas response') from error

    def prepare(self, claim):
        height, account_number, sequence = self.context(claim)
        tx, address = claim['transaction'], claim['account']['address']
        timeout = height + self.timeout_blocks if self.timeout_blocks else 0
        unsigned = self.cli.generate(tx, address, self.node.chain_id, timeout, self.max_gas, '', account_number, sequence)
        priced = unsigned['body']['messages'][0]['@type'] in ('/structs.structs.MsgGuildCreate', '/structs.structs.MsgReactorRestart')
        if priced and self.gas_price is None:
            raise PreparationUnavailable('Paid operations require an explicitly configured gas price')
        estimate_raw = self.cli.sign(unsigned, address, self.node.chain_id, account_number, sequence)
        # CLI generation/signing may cross a block boundary. Refresh the
        # account context before current-state simulation instead of requiring
        # all offline work to finish inside one block (especially on emulated
        # containers). A changed signer sequence still invalidates these bytes.
        height, current_number, current_sequence = self.context(claim)
        if (current_number, current_sequence) != (account_number, sequence):
            raise PreparationUnavailable('Signing account changed during preparation')
        if timeout and height >= timeout:
            raise PreparationUnavailable('Preparation exceeded its timeout window')
        used = self.simulate(estimate_raw, height)
        gas = max(1, (used * 13 + 9) // 10)
        if gas > self.max_gas:
            raise InvalidRequest('Simulated transaction exceeds the configured gas budget')
        with localcontext() as context:
            context.prec = 100
            amount = int((self.gas_price * gas).to_integral_value(rounding=ROUND_CEILING)) if priced else 0
        uint(amount)
        unsigned['auth_info']['fee']['gas_limit'] = str(gas)
        unsigned['auth_info']['fee']['amount'] = [{'denom': 'ualpha', 'amount': str(amount)}] if amount else []
        raw = self.cli.sign(unsigned, address, self.node.chain_id, account_number, sequence)
        return Signed(raw, account_number, sequence, height, timeout)

    def preflight(self, claim, saved):
        height, account_number, sequence = self.context(claim)
        if account_number != uint(saved['account_number']) or sequence != uint(saved['sequence']):
            raise InvalidRequest('Unsent transaction account state has changed')
        timeout = uint(saved['timeout_height'])
        if timeout and height >= timeout:
            raise InvalidRequest('Unsent transaction expired before transport began')
        self.simulate(saved['raw'], height)
