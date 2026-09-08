from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.model_artifacts import latest_registry_scores_path  # noqa: E402


class ModelArtifactPathTests(unittest.TestCase):
    def test_latest_registry_score_wins_over_stale_legacy_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quant_dir = root / "quant_data"
            models_dir = quant_dir / "models"
            old_candidate = quant_dir / "model_registry" / "CN" / "old" / "inference_scores_latest.parquet"
            new_candidate = quant_dir / "model_registry" / "CN" / "new" / "inference_scores_latest.parquet"
            legacy = models_dir / "inference_scores_latest.parquet"
            for path in (legacy, old_candidate, new_candidate):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(path.parent.name.encode())
            old_candidate.touch()
            new_candidate.touch()
            old_candidate_mtime = new_candidate.stat().st_mtime_ns - 1_000_000
            old_candidate.touch()
            import os

            os.utime(old_candidate, ns=(old_candidate_mtime, old_candidate_mtime))
            settings = SimpleNamespace(quant_dir=quant_dir, models_dir=models_dir)

            self.assertEqual(latest_registry_scores_path(settings), new_candidate)

    def test_legacy_path_is_used_when_registry_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quant_dir = Path(tmp) / "quant_data"
            models_dir = quant_dir / "models"
            settings = SimpleNamespace(quant_dir=quant_dir, models_dir=models_dir)

            self.assertEqual(
                latest_registry_scores_path(settings),
                models_dir / "inference_scores_latest.parquet",
            )


if __name__ == "__main__":
    unittest.main()
