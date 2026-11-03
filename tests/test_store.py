"""Exercise recovery selection and pagination against relational fixtures."""
import sqlite3
import unittest

from tsa.store import Store


class Connection:
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute("ATTACH DATABASE ':memory:' AS signer")
        self.db.execute('CREATE TABLE signer.tx(id INTEGER PRIMARY KEY, contract TEXT, status TEXT)')
        self.db.execute('CREATE TABLE signer.tx_submission(tx_id INTEGER PRIMARY KEY, state TEXT)')

    def execute(self, sql, parameters=()):
        return self.db.execute(sql.replace('%s', '?'), parameters)


class RecoveryTests(unittest.TestCase):
    def test_terminal_history_does_not_delay_active_or_unsigned_claims(self):
        store = Store.__new__(Store)
        store.connection = Connection()
        self.addCleanup(store.connection.db.close)
        for tx_id in range(1, 1343):
            store.connection.execute("INSERT INTO signer.tx VALUES (%s,'v022-1','broadcast')", (tx_id,))
            store.connection.execute("INSERT INTO signer.tx_submission VALUES (%s,'committed')", (tx_id,))
        states = ['accepted', 'prepared', 'sending', 'unknown', None, 'rejected', 'cancelled']
        for tx_id, state in enumerate(states, 1343):
            store.connection.execute("INSERT INTO signer.tx VALUES (%s,'v022-1','claimed')", (tx_id,))
            if state:
                store.connection.execute('INSERT INTO signer.tx_submission VALUES (%s,%s)', (tx_id, state))
        store.connection.execute("INSERT INTO signer.tx VALUES (1350,NULL,'claimed')")
        store.connection.execute("INSERT INTO signer.tx VALUES (1351,'v022-1','pending')")
        self.assertEqual(store.recovery(limit=2), [1343, 1344])
        self.assertEqual(store.recovery(after_id=1344, limit=2), [1345, 1346])
        self.assertEqual(store.recovery(after_id=1346, limit=2), [1347])
        self.assertEqual(store.recovery(after_id=1347), [])


if __name__ == '__main__':
    unittest.main()
