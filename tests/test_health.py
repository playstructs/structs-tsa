import unittest
from tsa.health import health_reason
from tsa.inventory import Inventory, NodeProtocolUnavailable
from unittest.mock import Mock

class HealthTests(unittest.TestCase):
    def test_health_thresholds_and_safe_reasons(self):
        healthy = dict(state='running', heartbeat=1000, inventory=1000, ready=True)
        self.assertIsNone(health_reason(healthy, 1089))
        self.assertEqual(health_reason(healthy, 1090), 'heartbeat-stale')
        self.assertEqual(health_reason(dict(healthy, heartbeat=1120), 1120), 'inventory-stale')
        self.assertEqual(health_reason(dict(healthy, ready=False), 1000), 'no-ready-signing-key')
        self.assertEqual(health_reason(dict(healthy, state='stopped'), 1000), 'worker-not-running')
        self.assertEqual(health_reason(dict(healthy, inventory_error='NodeProtocolUnavailable'), 1000), 'local-node-protocol-unavailable')
        self.assertEqual(health_reason(dict(healthy, inventory=0, inventory_error='secret'), 1000), 'inventory-stale')

    def test_fallback_is_healthy_but_unavailable_or_stale_pair_is_not(self):
        status = dict(state='running', heartbeat=1000, inventory=1000, ready=True)
        for mode in ['primary', 'fallback']:
            self.assertIsNone(health_reason(dict(status, endpoint={'mode': mode, 'checked_at': 1000}), 1001))
        self.assertEqual(health_reason(dict(status, endpoint={'mode': 'unavailable', 'checked_at': 1000}), 1001),
                         'chain-endpoints-unavailable')
        self.assertEqual(health_reason(dict(status, endpoint={'mode': 'fallback', 'checked_at': 910}), 1000),
                         'chain-endpoint-check-stale')

    def test_old_node_does_not_activate_keys(self):
        store, node, lcd, keys, volume, journal = [Mock() for _ in range(6)]
        keys.inventory.return_value = []
        store.readiness.return_value = dict(transaction_ready=True, protocol='v0.22.0')
        node.call.return_value = {'response': {'version': '0.21.0'}}
        with self.assertRaises(NodeProtocolUnavailable):
            Inventory(store, node, lcd, keys, volume, journal).run()
        store.reconcile_key.assert_not_called()
