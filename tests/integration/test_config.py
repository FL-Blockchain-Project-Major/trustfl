"""
Integration test asserting environment and configuration sanity.
"""

import unittest
from pathlib import Path


class TestConfig(unittest.TestCase):
    def test_env_example_exists(self) -> None:
        root = Path(__file__).resolve().parent.parent.parent
        env_example = root / ".env.example"
        self.assertTrue(env_example.is_file(), ".env.example must exist")
        content = env_example.read_text()
        self.assertIn("COORDINATOR_PORT", content)
        self.assertIn("BLOCKCHAIN_RPC_URL", content)
        self.assertIn("STORAGE_BACKEND", content)


if __name__ == "__main__":
    unittest.main()
