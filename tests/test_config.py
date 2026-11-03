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


if __name__ == '__main__':
    unittest.main()
