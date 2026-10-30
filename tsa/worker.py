"""The database commit, rather than a process timer, owns each send permit."""
from dataclasses import dataclass

from .rpc import RpcError, tx_hash, uint


class PreparationUnavailable(Exception):
    """Transient preflight failure: retain the unsigned claim for a later pass."""


class InvalidRequest(Exception):
    """Definitively invalid, still-unsent request. Contains a safe public reason."""


@dataclass(frozen=True)
class Signed:
    raw: bytes
    account_number: int
    sequence: int
    source_height: int
    timeout_height: int


def submission(value):
    if value is None:
        return None
    saved = dict(value)
    encoded = saved.get('signed_bytes')
    if not isinstance(encoded, str) or not encoded.startswith('\\x'):
        raise ValueError('Stored signed transaction is not PostgreSQL hex bytea')
    raw = bytes.fromhex(encoded[2:])
    if not 1 <= len(raw) <= 1048576 or tx_hash(raw) != saved.get('tx_hash'):
        raise ValueError('Stored transaction hash does not match its signed bytes')
    saved['raw'] = raw
    for field in ('account_number', 'sequence', 'source_height', 'timeout_height'):
        uint(saved.get(field))
    return saved


class Worker:
    def __init__(self, store, node, signer, journal=None):
        self.store = store
        self.node = node
        self.signer = signer
        self.journal = journal

    def observe(self, saved):
        if saved['state'] == 'sending':
            self.store.unknown(saved, 'Worker recovery is observing the persisted send identity')
        try:
            result = self.node.committed(saved)
        except RpcError:
            return 'awaiting-evidence'
        if result is None:
            return 'awaiting-inclusion'
        self.store.result(saved, result)
        if self.journal is not None:
            self.journal.finish(saved, result)
        return 'committed'

    def process(self, tx_id):
        # A dedicated DB connection holds this session lock through signing,
        # persistence and transport. No SQL transaction stays open during I/O.
        with self.store.lease(tx_id) as acquired:
            if not acquired:
                return 'busy'
            claim = self.store.claimed(tx_id)
            if claim is None:
                return 'inactive'
            saved = submission(self.store.submission(tx_id))
            if saved is not None and saved['state'] in ('sending', 'unknown', 'accepted'):
                return self.observe(saved)
            if saved is not None and saved['state'] != 'prepared':
                return 'terminal'
            try:
                if saved is None:
                    signed = self.signer.prepare(claim)
                    saved = submission(self.store.save(claim, signed))
                self.signer.preflight(claim, saved)
            except InvalidRequest as error:
                # Only an unsigned claim or a durable prepared identity can
                # reach here. SQL refuses cancellation after a send marker.
                self.store.abort(claim, str(error))
                if self.journal is not None and saved is not None:
                    self.journal.finish(saved, {'stage': 'unsent', 'code': 'cancelled', 'hash': saved['tx_hash']})
                return 'unsent-rejected'
            except (PreparationUnavailable, RpcError):
                return 'preflight-unavailable'

            # If this commit fails or its acknowledgement is lost, propagate
            # the DB error and perform no network write. Recovery reads the
            # persisted state; only a confirmed TRUE grants this one attempt.
            if self.journal is not None:
                self.journal.begin(claim, saved)
            if self.store.begin(saved) is not True:
                return 'send-not-permitted'
            try:
                result = self.node.broadcast(saved['raw'])
            except RpcError:
                self.store.unknown(saved, 'Broadcast response unavailable; observe the saved transaction hash')
                return 'unknown'
            # An unavailable result commit is not permission to send again.
            self.store.result(saved, result)
            if self.journal is not None and result['code'] != '0':
                self.journal.finish(saved, result)
            return 'accepted' if result['code'] == '0' else 'rejected'
