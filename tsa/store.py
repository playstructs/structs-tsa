"""Parameterized SQL adapter; every mutation commits before returning."""
from contextlib import contextmanager


class Store:
    LOCK_NAMESPACE = 223300

    def __init__(self, dsn):
        import psycopg
        self.connection = psycopg.connect(dsn, autocommit=True, connect_timeout=10,
                                         application_name='structs-tsa-v022')
        self.connection.execute("SET statement_timeout='15s'")
        self.connection.execute("SET lock_timeout='5s'")
        self.connection.execute("SET synchronous_commit='on'")

    def close(self):
        self.connection.close()

    def scalar(self, statement, parameters=()):
        return self.connection.execute(statement, parameters).fetchone()[0]

    @contextmanager
    def lease(self, tx_id):
        acquired = self.scalar('SELECT pg_try_advisory_lock(%s,%s)', (self.LOCK_NAMESPACE, tx_id))
        try:
            yield acquired
        finally:
            if acquired and not self.connection.closed:
                self.scalar('SELECT pg_advisory_unlock(%s,%s)', (self.LOCK_NAMESPACE, tx_id))

    def claim(self, inventory_id):
        return self.scalar('SELECT signer.CLAIM_TRANSACTION_V022(%s::uuid)', (inventory_id,))

    def claimed(self, tx_id):
        return self.scalar("""SELECT (SELECT jsonb_build_object('transaction',to_jsonb(t),'account',to_jsonb(a))
            FROM signer.tx t JOIN signer.account a ON a.id=t.account_id
            WHERE t.id=%s AND t.contract='v022-1' AND t.status IN ('claimed','broadcast'))""", (tx_id,))

    def recovery(self, after_id=0, limit=32):
        # Broadcast queue rows are retained after commitment. Page only active
        # submissions, plus claims that crashed before signed bytes were saved.
        return [row[0] for row in self.connection.execute("""SELECT id FROM (
            SELECT s.tx_id AS id FROM signer.tx_submission s
            WHERE s.state IN ('prepared','sending','unknown','accepted') AND s.tx_id>%s
            UNION ALL
            SELECT t.id FROM signer.tx t
            WHERE t.contract='v022-1' AND t.status='claimed' AND t.id>%s
                AND NOT EXISTS (SELECT 1 FROM signer.tx_submission s WHERE s.tx_id=t.id)
            ) active ORDER BY id LIMIT %s""", (after_id, after_id, limit))]

    def submission(self, tx_id):
        return self.scalar('SELECT signer.SUBMISSION_V022(%s)', (tx_id,))

    def save(self, claim, signed):
        tx = claim['transaction']
        return self.scalar('SELECT signer.SAVE_SIGNED_TRANSACTION_V022(%s,%s,%s,%s,%s,%s,%s)',
            (tx['id'], tx['claim_token'], signed.raw, signed.account_number, signed.sequence,
             signed.source_height, signed.timeout_height))

    def begin(self, saved):
        return self.scalar('SELECT signer.BEGIN_SUBMISSION_V022(%s,%s)', (saved['tx_id'], saved['claim_token']))

    def unknown(self, saved, reason):
        return self.scalar('SELECT signer.MARK_SUBMISSION_UNKNOWN_V022(%s,%s,%s)',
                           (saved['tx_id'], saved['claim_token'], reason))

    def result(self, saved, result):
        from psycopg.types.json import Jsonb
        return self.scalar('SELECT signer.RECORD_SUBMISSION_RESULT_V022(%s,%s,%s)',
                           (saved['tx_id'], saved['claim_token'], Jsonb(result)))

    def abort(self, claim, reason):
        tx = claim['transaction']
        return self.scalar('SELECT signer.ABORT_UNSENT_TRANSACTION_V022(%s,%s,%s)',
                           (tx['id'], tx['claim_token'], reason))

    @contextmanager
    def account_lease(self, account_id):
        acquired = self.scalar('SELECT pg_try_advisory_lock(%s,%s)', (self.LOCK_NAMESPACE + 1, account_id))
        try:
            yield acquired
        finally:
            if acquired and not self.connection.closed:
                self.scalar('SELECT pg_advisory_unlock(%s,%s)', (self.LOCK_NAMESPACE + 1, account_id))

    def claim_account(self):
        return self.scalar('SELECT signer.CLAIM_ACCOUNT_V022()')

    def account_request(self, account_id):
        return self.scalar('SELECT signer.ACCOUNT_REQUEST_V022(%s)', (account_id,))

    def account_recovery(self, after_id=0, limit=32):
        return [row[0] for row in self.connection.execute("""SELECT a.id FROM signer.account a
            JOIN signer.account_request q ON q.account_id=a.id
            WHERE a.status IN ('generating','pending') AND a.id>%s ORDER BY a.id LIMIT %s""", (after_id, limit))]

    def bind_account(self, account_id, address):
        return self.scalar('SELECT signer.BIND_REQUEST_ACCOUNT_V022(%s,%s)', (account_id, address))

    def register_account(self, request, proof, context):
        from psycopg.types.json import Jsonb
        return self.scalar('SELECT signer.UPDATE_PENDING_ACCOUNT(%s,%s,%s,%s,%s,%s,%s)',
                           (request['id'], request['player_id'], request['address'], proof['pubkey'],
                            proof['signature'], int(request['permissions']), Jsonb(context)))

    def account_ready(self, account_id, tx_id):
        return self.scalar('SELECT signer.ACCOUNT_REGISTRATION_READY_V022(%s,%s)', (account_id, tx_id))

    def activate_account(self, account_id, tx_id):
        return self.scalar('SELECT signer.ACTIVATE_ACCOUNT_V022(%s,%s)', (account_id, tx_id))

    def registration_failed(self, tx_id):
        return self.scalar('SELECT signer.REGISTRATION_FAILED_V022(%s)', (tx_id,))

    def renew_account(self, account_id, tx_id, proof, context):
        from psycopg.types.json import Jsonb
        return self.scalar('SELECT signer.RENEW_ACCOUNT_REGISTRATION_V022(%s,%s,%s,%s)',
                           (account_id, tx_id, proof['signature'], Jsonb(context)))

    def readiness(self):
        return self.scalar("SELECT to_jsonb(r) FROM structs.api_readiness(ARRAY[]::TEXT[]) r")

    def sync_keys(self, inventory_id, keys):
        from psycopg.types.json import Jsonb
        self.scalar('SELECT signer.SYNC_LOCAL_KEYS_V022(%s::uuid,%s)', (inventory_id, Jsonb(keys)))

    def reconcile_key(self, inventory_id, address, chain, height, tip, player, permissions, held):
        return self.scalar('SELECT signer.RECONCILE_LOCAL_KEY_V022(%s::uuid,%s,%s,%s,%s,%s,%s,%s)',
                           (inventory_id, address, chain, height, tip, player, permissions, held))

    def invalidate_key(self, inventory_id, address):
        self.scalar('SELECT signer.INVALIDATE_LOCAL_KEY_V022(%s::uuid,%s)', (inventory_id, address))

    def matching_submission(self, saved):
        return self.scalar("""SELECT (SELECT signer.SUBMISSION_V022(s.tx_id) || jsonb_build_object(
                'account_reserved',a.status='signing' AND t.status IN ('claimed','broadcast'))
            FROM signer.tx_submission s JOIN signer.account a ON a.id=s.account_id
            JOIN signer.tx t ON t.id=s.tx_id
            WHERE s.tx_id=%s AND s.claim_token=%s::uuid AND s.tx_hash=%s AND s.address=%s AND s.chain_id=%s)""",
            (saved['tx_id'], saved['claim_token'], saved['tx_hash'], saved['address'], saved['chain_id']))

    def pool_candidates(self, inventory_id, after_id=0, limit=32):
        return self.scalar("""WITH pending AS MATERIALIZED (
            SELECT * FROM signer.tx WHERE contract='v022-1' AND status='pending' AND id>%s ORDER BY id LIMIT %s
        ), candidates AS (
            SELECT jsonb_build_object('transaction',to_jsonb(t),'account',a.account,'permissions',a.permissions,
                'source_context',jsonb_build_object('chain_id',t.chain_id,'player_id',t.requested_player_id,
                    'address',a.account->>'address','created_at',extract(epoch FROM t.created_at)::text)) item
            FROM pending t CROSS JOIN LATERAL (
                SELECT to_jsonb(account) account,p.val::text permissions
                FROM signer.WORKER_AUTHORIZED_ACCOUNTS_V022(t.id) eligible
                JOIN signer.account ON account.id=eligible.account_id
                JOIN signer.local_key k ON k.address=account.address AND k.inventory_id=%s::uuid
                JOIN structs.permission p ON p.id='8-' || account.address || '@0'
                WHERE account.status='signing' AND k.present AND k.state='ready'
                    AND k.observed_at>NOW()-INTERVAL '120 seconds'
                ORDER BY bit_count(p.val::bit(25)),account.id LIMIT 1
            ) a WHERE NOT EXISTS (SELECT 1 FROM signer.WORKER_AUTHORIZED_ACCOUNTS_V022(t.id) eligible
                JOIN signer.local_key k ON k.address=eligible.address AND k.inventory_id=%s::uuid
                WHERE eligible.status='available' AND k.present AND k.state='ready'
                    AND k.observed_at>NOW()-INTERVAL '120 seconds')
        ) SELECT jsonb_build_object('cursor',COALESCE((SELECT max(id) FROM pending),0),
            'candidates',COALESCE((SELECT jsonb_agg(item) FROM candidates),'[]'::jsonb))""",
            (after_id, limit, inventory_id, inventory_id))

    def request_pool_account(self, inventory_id, intent):
        from psycopg.types.json import Jsonb
        return self.scalar('SELECT signer.REQUEST_POOL_ACCOUNT_V022(%s::uuid,%s,%s,%s,%s,%s,%s::uuid,%s)',
            (inventory_id, intent['role_id'], intent['source_account_id'], intent['tx_id'],
             int(intent['permissions']), intent['max_accounts'], intent['request_id'], Jsonb(intent['source_context'])))

    @contextmanager
    def role_lease(self, role_id):
        acquired = self.scalar('SELECT pg_try_advisory_lock(%s,%s)', (self.LOCK_NAMESPACE + 2, role_id))
        try:
            yield acquired
        finally:
            if acquired and not self.connection.closed:
                self.scalar('SELECT pg_advisory_unlock(%s,%s)', (self.LOCK_NAMESPACE + 2, role_id))

    def role_recovery(self, after_id=0, limit=4):
        return [row[0] for row in self.connection.execute("""SELECT role_id FROM (
            SELECT role_id FROM structs.player_internal_pending WHERE role_id>%s
            UNION SELECT role_id FROM signer.role_key_request WHERE role_id>%s AND NOT activated
            ) requests ORDER BY role_id LIMIT %s""", (after_id, after_id, limit))]

    def prepare_role(self, role_id, permissions):
        return self.scalar('SELECT signer.PREPARE_ROLE_KEY_V022(%s,%s)', (role_id, permissions))

    def bind_role(self, role_id, request_id, address, proof):
        return self.scalar('SELECT signer.BIND_ROLE_KEY_V022(%s,%s::uuid,%s,%s,%s)',
            (role_id, request_id, address, proof['pubkey'], proof['signature']))

    def activate_role(self, role_id, request_id, player_id, height, tip):
        return self.scalar('SELECT signer.ACTIVATE_ROLE_KEY_V022(%s,%s::uuid,%s,%s,%s)',
            (role_id, request_id, player_id, height, tip))
