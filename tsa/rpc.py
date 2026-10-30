"""Bounded CometBFT transport. Broadcast is one attempt, never an HTTP retry."""
import base64
import hashlib
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class RpcError(Exception):
    """Unavailable or untrusted transport evidence; never a terminal tx result."""


class RpcResponseError(RpcError):
    def __init__(self, error):
        super().__init__('RPC returned an error')
        self.error = error


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        return None


def uint(value, maximum=(1 << 64) - 1):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r'0|[1-9][0-9]*', value) or len(value) > 20:
        raise RpcError('Expected an exact unsigned integer')
    result = int(value)
    if result > maximum:
        raise RpcError('Unsigned integer exceeds its range')
    return result


def tx_hash(raw):
    return hashlib.sha256(raw).hexdigest().upper()


def decode_bytes(value):
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise RpcError('Invalid encoded transaction') from error


def result_fields(result):
    if not isinstance(result, dict) or 'code' not in result:
        raise RpcError('Missing transaction result code')
    fields = {'code': str(uint(result['code'], (1 << 32) - 1))}
    for name, limit in [('codespace', 128), ('log', 8192)]:
        value = result.get(name, '')
        if not isinstance(value, str) or len(value) > limit:
            raise RpcError('Invalid transaction result text')
        fields[name] = value
    return fields


class Node:
    def __init__(self, url, chain_id, timeout=10):
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('RPC URL must be an HTTP(S) endpoint without embedded credentials')
        self.url = url
        self.chain_id = chain_id
        self.timeout = timeout
        # Redirecting/replaying a POST must never turn one send into two.
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, method, params, limit=4 * 1024 * 1024):
        request = urllib.request.Request(self.url, method='POST',
            data=json.dumps({'jsonrpc': '2.0', 'id': 'tsa', 'method': method, 'params': params}).encode(),
            headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise RpcError('RPC response exceeds limit')
            body = json.loads(raw)
            if not isinstance(body, dict) or body.get('id') != 'tsa' or body.get('jsonrpc') != '2.0':
                raise RpcError('Invalid RPC envelope')
            if 'error' in body:
                raise RpcResponseError(body['error'])
            if not isinstance(body.get('result'), dict):
                raise RpcError('Missing RPC result')
            return body['result']
        except (OSError, ValueError, urllib.error.URLError) as error:
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            raise RpcError('RPC transport unavailable or malformed') from error

    def height(self):
        status = self.call('status', {})
        if status.get('node_info', {}).get('network') != self.chain_id:
            raise RpcError('RPC chain identity mismatch')
        sync = status.get('sync_info', {})
        if sync.get('catching_up') is not False:
            raise RpcError('RPC node is not current')
        height = uint(sync.get('latest_block_height'), (1 << 53) - 1)
        if height < 3353000:
            raise RpcError('v0.22 worker requires the activated protocol')
        return height

    def broadcast(self, raw):
        result = self.call('broadcast_tx_sync', {'tx': base64.b64encode(raw).decode()})
        expected = tx_hash(raw)
        if result.get('hash') != expected:
            raise RpcError('Admission hash does not match saved signed bytes')
        return {'stage': 'check_tx', 'hash': expected, **result_fields(result)}

    def committed(self, saved):
        """An index hit alone is insufficient: verify its block bytes and result."""
        expected = saved['tx_hash']
        try:
            result = self.call('tx', {'hash': base64.b64encode(bytes.fromhex(expected)).decode(), 'prove': False})
        except RpcResponseError as error:
            details = error.error
            # Absence is only a reason to keep observing, never proof of failure.
            if isinstance(details, dict) and details.get('code') == -32603 and isinstance(details.get('data'), str):
                if re.fullmatch(r'tx \(' + expected + r'\) not found', details['data'], re.IGNORECASE):
                    return None
            raise
        height = uint(result.get('height'), (1 << 53) - 1)
        index = uint(result.get('index'), (1 << 32) - 1)
        if result.get('hash') != expected or decode_bytes(result.get('tx')) != saved['raw'] or height < uint(saved['source_height']):
            raise RpcError('Transaction lookup does not match its saved identity')
        block = self.call('block', {'height': str(height)}, limit=64 * 1024 * 1024)
        header = block.get('block', {}).get('header', {})
        block_hash = block.get('block_id', {}).get('hash')
        if header.get('chain_id') != self.chain_id or uint(header.get('height')) != height:
            raise RpcError('Inclusion block has a different chain or height')
        if not isinstance(block_hash, str) or not re.fullmatch('[0-9A-F]{64}', block_hash):
            raise RpcError('Invalid inclusion block hash')
        transactions = block.get('block', {}).get('data', {}).get('txs')
        if not isinstance(transactions, list) or index >= len(transactions) or decode_bytes(transactions[index]) != saved['raw']:
            raise RpcError('Saved transaction is not at the reported block index')
        results = self.call('block_results', {'height': str(height)}, limit=64 * 1024 * 1024)
        items = results.get('txs_results')
        if uint(results.get('height')) != height or not isinstance(items, list) or index >= len(items):
            raise RpcError('Missing results for the inclusion block')
        outcome = result_fields(items[index])
        if outcome != result_fields(result.get('tx_result')):
            raise RpcError('Indexed outcome differs from the block result')
        return {'stage': 'deliver_tx', 'hash': expected, 'height': str(height), 'index': str(index),
                'block_hash': block_hash, **outcome}
