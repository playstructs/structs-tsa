"""Small explicit runtime configuration; never print connection credentials."""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Config:
    database: str
    chain_id: str
    rpc: str
    lcd: str
    keyring: str
    home: str
    workers: int
    pool_maximum: int
    gas_price: str | None
    rpc_fallback: str | None = None
    lcd_fallback: str | None = None

    @classmethod
    def from_environment(cls):
        database = os.environ.get('DATABASE_URL')
        if not database:
            raise ValueError('DATABASE_URL is required')
        chain = os.environ.get('TSA_CHAIN_ID', os.environ.get('NETWORK_CHAIN_ID', 'structstestnet-111'))
        if chain != 'structstestnet-111':
            raise ValueError('This migration supports the configured v0.22 testnet only')
        workers = int(os.environ.get('TSA_WORKERS', os.environ.get('AGENT_TARGET_NUMBER', '6')))
        maximum = int(os.environ.get('TSA_ROLE_MAX_KEYS', '40'))
        if not 1 <= workers <= 128 or not 1 <= maximum <= 40:
            raise ValueError('Worker count must be 1..128 and role key limit 1..40')
        rpc_fallback = os.environ.get('TSA_RPC_FALLBACK_URL') or None
        lcd_fallback = os.environ.get('TSA_LCD_FALLBACK_URL') or None
        if bool(rpc_fallback) != bool(lcd_fallback):
            raise ValueError('TSA fallback requires both RPC and LCD URLs')
        return cls(database, chain, os.environ.get('TSA_RPC_URL', 'http://structsd:26657'),
                   os.environ.get('TSA_LCD_URL', 'http://structsd:1317'),
                   os.environ.get('TSA_KEYRING_DIR', '/var/structs/accounts'),
                   os.environ.get('TSA_HOME', '/var/structs/chain'), workers, maximum,
                   os.environ.get('TSA_GAS_PRICE') or None, rpc_fallback, lcd_fallback)
