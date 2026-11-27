import sys
from pathlib import Path

import pytest

_client_dir = str(Path(__file__).resolve().parents[3] / "apps" / "client")
if _client_dir not in sys.path:
    sys.path.insert(0, _client_dir)

from main import _build_train_fn  # noqa: E402


def test_build_train_fn_fails_closed_without_dataset():
    with pytest.raises(RuntimeError, match="Real YOLO training requires"):
        _build_train_fn(
            images_dir="",
            annotations_dir="",
            epochs=1,
            max_samples=10,
            allow_synthetic=False,
            environment="development",
        )


def test_build_train_fn_forbids_synthetic_in_production():
    with pytest.raises(RuntimeError, match="forbidden when ENVIRONMENT=production"):
        _build_train_fn(
            images_dir="",
            annotations_dir="",
            epochs=1,
            max_samples=10,
            allow_synthetic=True,
            environment="production",
        )


def test_build_train_fn_allows_explicit_synthetic_only_in_non_production():
    fn = _build_train_fn(
        images_dir="",
        annotations_dir="",
        epochs=1,
        max_samples=10,
        allow_synthetic=True,
        environment="development",
    )
    params, count, metrics = fn(1, [[0.1, 0.2]], {})
    assert len(params) == 1
    assert count == 50
    assert metrics.get("is_simulated") is True


def test_build_train_fn_fails_closed_on_missing_weights_in_production(tmp_path):
    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_dir.mkdir()
    ann_dir.mkdir()
    # Create one tiny valid image + annotation so dataset validation passes
    import cv2
    import numpy as np

    cv2.imwrite(str(img_dir / "img1.jpg"), np.zeros((32, 32, 3), dtype=np.uint8))
    (ann_dir / "img1.txt").write_text("2,2,10,10,1,1,0,0\n")

    with pytest.raises(FileNotFoundError):
        _build_train_fn(
            images_dir=str(img_dir),
            annotations_dir=str(ann_dir),
            epochs=1,
            max_samples=10,
            weights_path=str(tmp_path / "nonexistent.pt"),
            allow_synthetic=False,
            environment="production",
        )
