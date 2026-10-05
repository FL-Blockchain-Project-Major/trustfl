"""
Unit test asserting repository bootstrap and basic structure sanity.
"""

from pathlib import Path
import unittest


class TestBootstrap(unittest.TestCase):
    def test_repository_structure(self) -> None:
        expected_dirs = [
            "apps/coordinator",
            "apps/client",
            "apps/api",
            "apps/dashboard",
            "packages/schemas",
            "packages/crypto",
            "packages/blockchain-sdk",
            "packages/storage",
            "contracts",
            "zk",
            "datasets/tools",
            "infrastructure",
            "tests",
            "docs",
            "scripts",
        ]
        root = Path(__file__).resolve().parent.parent.parent
        for d in expected_dirs:
            dir_path = root / d
            self.assertTrue(dir_path.is_dir(), f"Expected directory '{d}' does not exist.")

    def test_zero_git_files_not_present(self) -> None:
        root = Path(__file__).resolve().parent.parent.parent
        forbidden_extensions = {
            ".pt",
            ".pth",
            ".bin",
            ".safetensors",
            ".onnx",
            ".npy",
            ".h5",
            ".key",
            ".pem",
        }
        for file in root.rglob("*"):
            # Skip third-party and build directories
            parts = file.parts
            if any(p in parts for p in ("node_modules", "__pycache__", ".git")):
                continue
            if file.is_file():
                self.assertNotIn(
                    file.suffix,
                    forbidden_extensions,
                    f"Forbidden file found in repository: {file}",
                )


if __name__ == "__main__":
    unittest.main()
