import os
import tempfile
import unittest
import hashlib
from unittest.mock import patch, MagicMock
from trustfl_storage.client import LocalStorageClient, IPFSStorageClient, compute_sha256

class TestStorage(unittest.TestCase):
    def test_local_storage_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = LocalStorageClient(tmpdir)
            data = b"model_weights_12345"
            expected_hash = compute_sha256(data)
            
            # 1. Upload/Save
            meta = client.save_artifact(
                data=data,
                model_version="v1.0",
                round_id=1,
                client_id="clientA",
                update_id="update1"
            )
            self.assertEqual(meta.sha256_hash, expected_hash)
            self.assertTrue(meta.uri.startswith("file://"))
            self.assertEqual(meta.size, len(data))
            
            # 2. Retrieval & Verification
            retrieved_data = client.load_artifact(meta.uri, expected_hash)
            self.assertEqual(retrieved_data, data)
            
            # 3. Hash Mismatch Detection
            with self.assertRaisesRegex(ValueError, "Hash mismatch"):
                client.load_artifact(meta.uri, "wrong_hash_123")
                
            # 4. Corruption Detection
            filepath = meta.uri[len("file://"):]
            with open(filepath, "wb") as f:
                f.write(b"corrupted_weights")
                
            with self.assertRaisesRegex(ValueError, "Hash mismatch"):
                client.load_artifact(meta.uri, expected_hash)

    @patch("trustfl_storage.client.requests.post")
    def test_ipfs_storage_lifecycle(self, mock_post):
        client = IPFSStorageClient("http://mock-ipfs:5001")
        data = b"ipfs_model_weights_999"
        expected_hash = compute_sha256(data)
        
        # Mock IPFS add
        mock_resp_add = MagicMock()
        mock_resp_add.json.return_value = {"Hash": "QmTest123", "Name": "artifact.bin", "Size": "22"}
        mock_resp_add.raise_for_status = MagicMock()
        
        # Mock IPFS cat
        mock_resp_cat = MagicMock()
        mock_resp_cat.content = data
        mock_resp_cat.raise_for_status = MagicMock()
        
        def mock_post_impl(url, **kwargs):
            if "/api/v0/add" in url:
                return mock_resp_add
            elif "/api/v0/cat" in url:
                return mock_resp_cat
            raise ValueError("Unknown URL")
            
        mock_post.side_effect = mock_post_impl
        
        # 1. Upload
        meta = client.save_artifact(
            data=data,
            model_version="v1.0",
            round_id=2
        )
        self.assertEqual(meta.uri, "ipfs://QmTest123")
        self.assertEqual(meta.sha256_hash, expected_hash)
        
        # 2. Retrieval
        retrieved_data = client.load_artifact(meta.uri, expected_hash)
        self.assertEqual(retrieved_data, data)
        
        # 3. Mismatch / CID corruption simulation
        # Return wrong data for the same CID
        mock_resp_cat_corrupted = MagicMock()
        mock_resp_cat_corrupted.content = b"hacked_model"
        
        def mock_post_impl_corrupted(url, **kwargs):
            if "/api/v0/cat" in url:
                return mock_resp_cat_corrupted
            return mock_resp_add
            
        mock_post.side_effect = mock_post_impl_corrupted
        
        with self.assertRaisesRegex(ValueError, "Hash mismatch"):
            client.load_artifact(meta.uri, expected_hash)

if __name__ == "__main__":
    unittest.main()
