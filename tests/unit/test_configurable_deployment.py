"""
Unit and integration tests for configurable Docker deployment milestone:
- Arbitrary client counts (1, 2, and 3 or more)
- Invalid client count validation
- Unique client identities and atomic slot claiming with persistent keys
- Shared dataset mounts without cross-client interference
- Missing and invalid dataset validation and error handling
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from apps.coordinator.network.server import CoordinatorState
from packages.crypto.trustfl_crypto.provision import (
    claim_client_identity,
    provision_client_identities,
    validate_client_counts,
)
from packages.ml_core.trustfl_ml.config import TrainingConfig
from packages.ml_core.trustfl_ml.dataset import (
    DatasetValidationError,
    resolve_and_validate_dataset,
)
from packages.ml_core.trustfl_ml.yolo_wrapper import SimulatedDetector


# ---------------------------------------------------------------------------
# Helper: Create valid synthetic dataset
# ---------------------------------------------------------------------------
def _create_valid_raw_dataset(
    root: Path,
    num_samples: int = 5,
    layout: str = "standard",
) -> Path:
    """Creates a small, fully valid VisDrone dataset in a temporary path."""
    if layout == "standard":
        img_dir = root / "images"
        ann_dir = root / "annotations"
    elif layout == "split":
        img_dir = root / "train" / "images"
        ann_dir = root / "train" / "annotations"
        val_img = root / "val" / "images"
        val_ann = root / "val" / "annotations"
        val_img.mkdir(parents=True, exist_ok=True)
        val_ann.mkdir(parents=True, exist_ok=True)
        # 1 val sample
        im_val = Image.new("RGB", (640, 480), color=(100, 150, 200))
        im_val.save(val_img / "val_001.jpg")
        (val_ann / "val_001.txt").write_text("50,50,100,100,1,1,0,0\n", encoding="utf-8")
    else:  # flat
        img_dir = root
        ann_dir = root

    img_dir.mkdir(parents=True, exist_ok=True)
    ann_dir.mkdir(parents=True, exist_ok=True)

    for i in range(1, num_samples + 1):
        stem = f"sample_{i:03d}"
        im = Image.new("RGB", (640, 480), color=(i * 20 % 255, 100, 150))
        im.save(img_dir / f"{stem}.jpg")
        (ann_dir / f"{stem}.txt").write_text(
            "10,10,100,80,1,1,0,0\n150,150,50,50,1,4,0,0\n",
            encoding="utf-8",
        )
    return root


# ---------------------------------------------------------------------------
# Test Suite 1: Client Count Configuration & Quorum Validation
# ---------------------------------------------------------------------------
class TestClientCountValidation:
    def test_valid_counts(self):
        num_c, min_c = validate_client_counts(1, 1)
        assert (num_c, min_c) == (1, 1)

        num_c, min_c = validate_client_counts(2, 2)
        assert (num_c, min_c) == (2, 2)

        num_c, min_c = validate_client_counts(5, 3)
        assert (num_c, min_c) == (5, 3)

        # Default min_clients is num_clients
        num_c, min_c = validate_client_counts(4)
        assert (num_c, min_c) == (4, 4)

    def test_invalid_num_clients(self):
        with pytest.raises(ValueError, match="FL_NUM_CLIENTS must be an integer >= 1"):
            validate_client_counts(0, 0)

        with pytest.raises(ValueError, match="FL_NUM_CLIENTS must be an integer >= 1"):
            validate_client_counts(-3, 1)

        with pytest.raises(ValueError, match="FL_NUM_CLIENTS must be an integer >= 1"):
            validate_client_counts(True)  # bool is not accepted as int

        with pytest.raises(ValueError, match="FL_NUM_CLIENTS must be an integer >= 1"):
            validate_client_counts("two")  # type: ignore

    def test_min_clients_greater_than_num_clients(self):
        with pytest.raises(ValueError, match="FL_MIN_CLIENTS .* cannot exceed FL_NUM_CLIENTS"):
            validate_client_counts(num_clients=2, min_clients=3)

        with pytest.raises(ValueError, match="FL_MIN_CLIENTS .* cannot exceed FL_NUM_CLIENTS"):
            validate_client_counts(num_clients=1, min_clients=2)

    def test_coordinator_min_clients_validation(self):
        with pytest.raises(ValueError, match="min_clients must be an integer >= 1"):
            CoordinatorState(min_clients=0, num_rounds=1)

        with pytest.raises(ValueError, match="min_clients must be an integer >= 1"):
            CoordinatorState(min_clients=-1, num_rounds=1)


# ---------------------------------------------------------------------------
# Test Suite 2: Unique Identities & Persistent Slot Claiming
# ---------------------------------------------------------------------------
class TestUniqueIdentitiesAndProvisioning:
    def test_provision_generates_allowlist_and_persistent_keys(self, tmp_path):
        keys_dir = tmp_path / "keys"
        allowlist = provision_client_identities(keys_dir, num_clients=3, min_clients=2)

        assert len(allowlist) == 3
        assert set(allowlist.keys()) == {"client_001", "client_002", "client_003"}

        # Check key files created with 0600 permissions
        for cid in allowlist:
            key_file = keys_dir / cid / "private.pem"
            assert key_file.is_file()
            stat = key_file.stat()
            assert (stat.st_mode & 0o777) == 0o600

        # Check allowlist.json written
        allowlist_json = keys_dir / "allowlist.json"
        assert allowlist_json.is_file()
        loaded = json.loads(allowlist_json.read_text(encoding="utf-8"))
        assert loaded == allowlist

        # Second provision run should reuse existing keys, not overwrite
        allowlist_second = provision_client_identities(keys_dir, num_clients=3, min_clients=2)
        assert allowlist_second == allowlist

    def test_atomic_slot_claiming_unique_ids(self, tmp_path):
        keys_dir = tmp_path / "keys"
        provision_client_identities(keys_dir, num_clients=3)

        # Worker 1 claims first available slot
        cid1, ident1, lock1 = claim_client_identity(keys_dir, num_clients=3)
        assert cid1 == "client_001"
        assert ident1.client_id == "client_001"

        # Worker 2 claims second available slot while lock1 is held
        cid2, ident2, lock2 = claim_client_identity(keys_dir, num_clients=3)
        assert cid2 == "client_002"
        assert ident2.client_id == "client_002"
        assert ident2.public_key_b64 != ident1.public_key_b64

        # Worker 3 claims third available slot while lock1 and lock2 are held
        cid3, ident3, lock3 = claim_client_identity(keys_dir, num_clients=3)
        assert cid3 == "client_003"
        assert ident3.client_id == "client_003"

        # All 3 slots in use; next worker must raise RuntimeError
        with pytest.raises(
            RuntimeError, match="all 3 client identity slots .* are currently in use"
        ):
            claim_client_identity(keys_dir, num_clients=3)

        # Releasing Worker 2 lock makes client_002 available again
        lock2.close()
        cid2_reclaimed, ident2_reclaimed, lock2_new = claim_client_identity(keys_dir, num_clients=3)
        assert cid2_reclaimed == "client_002"
        # Persistent identity: public key must match exactly!
        assert ident2_reclaimed.public_key_b64 == ident2.public_key_b64

        lock1.close()
        lock2_new.close()
        lock3.close()


# ---------------------------------------------------------------------------
# Test Suite 3: Dataset Resolution and Validation
# ---------------------------------------------------------------------------
class TestDatasetResolutionAndValidation:
    def test_resolve_standard_layout(self, tmp_path):
        ds_root = _create_valid_raw_dataset(tmp_path / "dataset", num_samples=3, layout="standard")
        res = resolve_and_validate_dataset(ds_root, min_samples=2)

        assert res["train_images_dir"] == ds_root / "images"
        assert res["train_annotations_dir"] == ds_root / "annotations"
        assert res["stats"]["valid_pairs"] == 3
        assert res["stats"]["total_boxes"] == 6

    def test_resolve_split_layout(self, tmp_path):
        ds_root = _create_valid_raw_dataset(tmp_path / "dataset", num_samples=4, layout="split")
        res = resolve_and_validate_dataset(ds_root, min_samples=1)

        assert res["train_images_dir"] == ds_root / "train" / "images"
        assert res["train_annotations_dir"] == ds_root / "train" / "annotations"
        assert res["val_images_dir"] == ds_root / "val" / "images"
        assert res["stats"]["valid_pairs"] == 4

    def test_resolve_flat_layout(self, tmp_path):
        ds_root = _create_valid_raw_dataset(tmp_path / "dataset", num_samples=2, layout="flat")
        res = resolve_and_validate_dataset(ds_root, min_samples=1)

        assert res["train_images_dir"] == ds_root
        assert res["train_annotations_dir"] == ds_root
        assert res["stats"]["valid_pairs"] == 2

    def test_missing_dataset_directory(self, tmp_path):
        missing = tmp_path / "non_existent_dir"
        with pytest.raises(DatasetValidationError, match="not found or not a directory"):
            resolve_and_validate_dataset(missing)

    def test_empty_dataset_directory(self, tmp_path):
        empty = tmp_path / "empty_ds"
        empty.mkdir()
        with pytest.raises(DatasetValidationError, match="Invalid dataset layout"):
            resolve_and_validate_dataset(empty)

    def test_corrupt_image_detection(self, tmp_path):
        ds_root = _create_valid_raw_dataset(tmp_path / "dataset", num_samples=2)
        # Corrupt one image
        bad_img = ds_root / "images" / "sample_001.jpg"
        bad_img.write_text("not an image at all", encoding="utf-8")

        with pytest.raises(DatasetValidationError, match="Failed to read image"):
            resolve_and_validate_dataset(ds_root)

    def test_corrupt_annotation_format(self, tmp_path):
        ds_root = _create_valid_raw_dataset(tmp_path / "dataset", num_samples=1)
        # Write invalid annotation line
        bad_ann = ds_root / "annotations" / "sample_001.txt"
        bad_ann.write_text("invalid,annotation,line\n", encoding="utf-8")

        with pytest.raises(DatasetValidationError, match="No matching image-annotation pairs"):
            resolve_and_validate_dataset(ds_root)

    def test_insufficient_sample_count(self, tmp_path):
        ds_root = _create_valid_raw_dataset(tmp_path / "dataset", num_samples=2)
        with pytest.raises(DatasetValidationError, match="at least 5 usable samples are required"):
            resolve_and_validate_dataset(ds_root, min_samples=5)


# ---------------------------------------------------------------------------
# Test Suite 4: Shared Dataset Mounts (Concurrent Multi-Client Safety)
# ---------------------------------------------------------------------------
class TestSharedDatasetMounts:
    def test_multiple_clients_read_shared_dataset_without_mutation(self, tmp_path):
        ds_root = _create_valid_raw_dataset(tmp_path / "shared_data", num_samples=4)

        # Snapshot modification times of raw dataset files
        initial_mtimes = {f: f.stat().st_mtime_ns for f in ds_root.rglob("*") if f.is_file()}

        # 3 simulated clients read and train on the exact same dataset
        clients = ["client_001", "client_002", "client_003"]
        model_updates = []

        for _cid in clients:
            ds_info = resolve_and_validate_dataset(ds_root, min_samples=1)
            model = SimulatedDetector()
            train_metrics = model.train_on_dataset(
                images_dir=ds_info["train_images_dir"],
                annotations_dir=ds_info["train_annotations_dir"],
                config=TrainingConfig(epochs=1),
                max_samples=10,
            )
            assert train_metrics["samples_trained"] == 4
            assert train_metrics["total_boxes"] == 8
            model_updates.append(model.get_parameters())

        # Verify raw dataset files were completely untouched
        after_mtimes = {f: f.stat().st_mtime_ns for f in ds_root.rglob("*") if f.is_file()}
        assert initial_mtimes == after_mtimes

        # Verify all client models produced compatible parameter shapes
        for p in model_updates:
            assert len(p) == len(model_updates[0])
            for l1, l2 in zip(p, model_updates[0], strict=False):
                assert len(l1) == len(l2)


# ---------------------------------------------------------------------------
# Test Suite 5: Training Lifecycle with Configurable Client Counts (1, 2, 3+)
# ---------------------------------------------------------------------------
class TestConfigurableClientLifecycle:
    def _run_lifecycle_test(self, num_clients: int, min_clients: int, tmp_path: Path):
        """Helper to run a full round lifecycle with N clients."""
        keys_dir = tmp_path / "keys"
        allowlist = provision_client_identities(keys_dir, num_clients=num_clients)

        # Create coordinator state
        state = CoordinatorState(
            min_clients=min_clients,
            num_rounds=1,
            require_signatures=False,
            round_timeout_seconds=10.0,
        )

        # Register all configured clients
        for i in range(1, num_clients + 1):
            cid = f"client_{i:03d}"
            ok = state.register_client(cid, {"pubkey": allowlist[cid]})
            assert ok is True

        # When min_clients registered, round 1 starts
        assert state.current_round == 1
        assert state._round_active is True

        # All clients fetch instructions, compute update, and submit
        global_params = state.global_parameters
        initial_params = global_params if global_params else [[0.1 * j for j in range(10)]]
        state.global_parameters = initial_params

        for i in range(1, num_clients + 1):
            cid = f"client_{i:03d}"
            instr = state.get_round_instructions(cid)
            assert instr["is_active"] is True
            assert instr["round_id"] == 1

            # Submit update
            client_params = [[v + 0.01 * i for v in layer] for layer in initial_params]
            accepted = state.submit_update(
                cid=cid,
                round_id=1,
                parameters=client_params,
                num_examples=25 * i,
                metrics={"loss": 0.5 / i},
            )
            assert accepted is True

        # When all active clients submit, aggregation should trigger and finalize round
        assert state.current_round == 2  # Advanced past round 1
        assert state._round_active is False
        assert state._done_event.is_set()
        assert len(state.round_history) == 1
        assert state.round_history[0]["num_successful_clients"] == num_clients

    def test_client_count_1(self, tmp_path):
        """Test with exactly 1 client worker (min_clients=1)."""
        self._run_lifecycle_test(num_clients=1, min_clients=1, tmp_path=tmp_path)

    def test_client_count_2(self, tmp_path):
        """Test with exactly 2 client workers (min_clients=2)."""
        self._run_lifecycle_test(num_clients=2, min_clients=2, tmp_path=tmp_path)

    def test_client_count_3(self, tmp_path):
        """Test with 3 client workers (min_clients=3)."""
        self._run_lifecycle_test(num_clients=3, min_clients=3, tmp_path=tmp_path)

    def test_client_count_4_with_min_clients_3(self, tmp_path):
        """Test with 4 configured workers where quorum threshold is 3."""
        self._run_lifecycle_test(num_clients=4, min_clients=3, tmp_path=tmp_path)
