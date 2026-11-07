"""Readiness diagnostics containing fixed reason codes, never exception text."""

def health_reason(status, now):
    if status.get('state') != 'running':
        return 'worker-not-running'
    if now - status.get('heartbeat', 0) >= 90:
        return 'heartbeat-stale'
    if status.get('inventory_error') == 'NodeProtocolUnavailable':
        return 'local-node-protocol-unavailable'
    if now - status.get('inventory', 0) >= 120:
        return 'inventory-stale'
    if status.get('ready') is not True:
        return 'no-ready-signing-key'
    return None
