"""Readiness diagnostics containing fixed reason codes, never exception text."""

def health_reason(status, now):
    if status.get('state') != 'running':
        return 'worker-not-running'
    if now - status.get('heartbeat', 0) >= 90:
        return 'heartbeat-stale'
    endpoint = status.get('endpoint')
    if endpoint is not None:
        if endpoint.get('mode') not in ('primary', 'fallback'):
            return 'chain-endpoints-unavailable'
        if now - endpoint.get('checked_at', 0) >= 90:
            return 'chain-endpoint-check-stale'
    if status.get('inventory_error') == 'EndpointsUnavailable':
        return 'chain-endpoints-unavailable'
    if status.get('inventory_error') == 'NodeProtocolUnavailable':
        return 'chain-node-protocol-unavailable' if endpoint is not None else 'local-node-protocol-unavailable'
    if now - status.get('inventory', 0) >= 120:
        return 'inventory-stale'
    if status.get('ready') is not True:
        return 'no-ready-signing-key'
    return None
