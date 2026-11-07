import os
import unittest
from unittest.mock import patch

from tsa.config import Config


class ConfigTests(unittest.TestCase):
    def test_worker_default_and_explicit_overrides(self):
        for settings, workers in [({}, 6), ({'AGENT_TARGET_NUMBER': '4'}, 4),
                                  ({'AGENT_TARGET_NUMBER': '30', 'TSA_WORKERS': '6'}, 6)]:
            with self.subTest(settings=settings), patch.dict(os.environ, dict(DATABASE_URL='unused', **settings), clear=True):
                self.assertEqual(Config.from_environment().workers, workers)

    def test_fallback_requires_a_complete_pair_and_can_be_disabled(self):
        for settings in [{}, {'TSA_RPC_FALLBACK_URL': '', 'TSA_LCD_FALLBACK_URL': ''}]:
            with patch.dict(os.environ, dict(DATABASE_URL='unused', **settings), clear=True):
                config = Config.from_environment()
                self.assertIsNone(config.rpc_fallback)
                self.assertIsNone(config.lcd_fallback)
        for variable in ['TSA_RPC_FALLBACK_URL', 'TSA_LCD_FALLBACK_URL']:
            with patch.dict(os.environ, {'DATABASE_URL': 'unused', variable: 'https://example.test'}, clear=True):
                with self.assertRaises(ValueError):
                    Config.from_environment()
        with patch.dict(os.environ, {'DATABASE_URL': 'unused', 'TSA_RPC_FALLBACK_URL': 'https://rpc.test',
                                     'TSA_LCD_FALLBACK_URL': 'https://lcd.test'}, clear=True):
            config = Config.from_environment()
            self.assertEqual((config.rpc_fallback, config.lcd_fallback), ('https://rpc.test', 'https://lcd.test'))


if __name__ == '__main__':
    unittest.main()
