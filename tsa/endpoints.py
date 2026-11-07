"""Select trusted RPC/LCD pairs between operations, never retry a broadcast."""
from dataclasses import dataclass
from threading import Lock
import time

from .rpc import Node, RpcError, uint
from .signer import Lcd
from .worker import PreparationUnavailable


class EndpointsUnavailable(PreparationUnavailable):
    """No configured endpoint pair passed the current readiness checks."""


@dataclass(frozen=True)
class EndpointPair:
    mode: str
    node: Node
    lcd: Lcd


class EndpointSelector:
    # Share probes across workers. Three spaced primary successes are required
    # after fallback, including when fallback subsequently becomes unavailable.
    PROBE_INTERVAL = 10
    RECOVERY_CHECKS = 3

    def __init__(self, config, monotonic=time.monotonic, wall_clock=time.time):
        self.primary = EndpointPair('primary', Node(config.rpc, config.chain_id), Lcd(config.lcd))
        self.fallback = None
        if bool(config.rpc_fallback) != bool(config.lcd_fallback):
            raise ValueError('TSA fallback requires both RPC and LCD URLs')
        if config.rpc_fallback:
            self.fallback = EndpointPair('fallback', Node(config.rpc_fallback, config.chain_id), Lcd(config.lcd_fallback))
        self.monotonic, self.wall_clock = monotonic, wall_clock
        self.lock = Lock()
        self.next_probe = 0
        self.selected = None
        self.recovering_primary = False
        self.primary_successes = 0
        self.status = {'mode': 'unavailable', 'checked_at': 0, 'failures': {}}

    @staticmethod
    def probe(pair, context):
        try:
            tip = pair.node.height()  # Chain identity, caught-up flag, activation height.
            version = pair.node.call('abci_info', {}).get('response', {}).get('version')
        except (RpcError, AttributeError, TypeError, ValueError):
            return 'rpc-unavailable'
        if version not in ('0.22.0', 'v0.22.0'):
            return 'rpc-protocol-unavailable'
        # Recovery of already-sent transactions must remain possible even when
        # the index is not ready to authorize new work. Existing signer and SQL
        # gates still independently validate every new signing attempt.
        if context and context.get('transaction_ready') is True:
            if context.get('chain_id') != pair.node.chain_id or context.get('protocol') != 'v0.22.0':
                return 'index-contract-mismatch'
            height = uint(context['indexed_height'])
            if not height <= tip <= height + 5:
                return 'index-height-mismatch'
        try:
            info = pair.lcd.get('/cosmos/base/tendermint/v1beta1/node_info', tip)
        except (PreparationUnavailable, RpcError):
            return 'lcd-unavailable'
        if not isinstance(info, dict) or not isinstance(info.get('default_node_info'), dict) \
                or info['default_node_info'].get('network') != pair.node.chain_id:
            return 'lcd-chain-mismatch'
        if not isinstance(info.get('application_version'), dict) \
                or info['application_version'].get('version') not in ('0.22.0', 'v0.22.0'):
            return 'lcd-protocol-unavailable'
        return None

    def select(self, context=None):
        with self.lock:
            now = self.monotonic()
            if now >= self.next_probe:
                failures = {}
                primary_error = self.probe(self.primary, context)
                if primary_error:
                    failures['primary'] = primary_error
                    self.primary_successes = 0
                else:
                    self.primary_successes += 1
                selected = None
                if not primary_error and (not self.recovering_primary or self.primary_successes >= self.RECOVERY_CHECKS):
                    selected = self.primary
                    self.recovering_primary = False
                elif self.fallback:
                    fallback_error = self.probe(self.fallback, context)
                    if fallback_error:
                        failures['fallback'] = fallback_error
                    else:
                        selected = self.fallback
                        self.recovering_primary = True
                self.selected = selected
                self.status = {'mode': selected.mode if selected else 'unavailable',
                               'checked_at': self.wall_clock(), 'failures': failures}
                self.next_probe = self.monotonic() + self.PROBE_INTERVAL
            if self.selected is None:
                raise EndpointsUnavailable('No verified chain endpoint pair is available')
            # Clients are concrete and never change underneath a caller. A
            # later selection affects only subsequent operations.
            return self.selected

    def snapshot(self):
        # Published status objects are replaced, never mutated. Reporting must
        # not wait behind a slow network probe and stall the heartbeat.
        status = self.status
        return dict(status, failures=dict(status['failures']))
