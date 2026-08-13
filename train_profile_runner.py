#!/usr/bin/env python3
"""Train and score one or more configured model profiles."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from model_registry_artifacts import create_model_registry_snapshot


DEFAULT_CATALOG = "run/model_profiles.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train LightGBM artifacts for model profiles.")
    parser.add_argument("--profiles", default="all", help="Profile name, comma-separated profile names, or 'all'.")
    parser.add_argument("--catalog-path", default=DEFAULT_CATALOG)
    parser.add_argument("--data-dir", default="quant_data")
    parser.add_argument("--inference-path", default="quant_data/inference_features_latest.parquet")
    # Accepted as no-ops so a pipeline coordinator that was already running during
    # this migration cannot fall back to the former mutable file-copy deployment.
    parser.add_argument("--sync-active", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--active-profile", default="", help=argparse.SUPPRESS)
    return parser.parse_args()


def read_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"profile catalog not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"failed to load profile catalog {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"profile catalog must be a JSON object: {path}")
    return payload


def profiles_by_name(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_profiles = catalog.get("profiles")
    if not isinstance(raw_profiles, list):
        raise SystemExit("profile catalog is missing a profiles array")
    profiles: dict[str, dict[str, Any]] = {}
    for item in raw_profiles:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            profiles[name] = item
    if not profiles:
        raise SystemExit("profile catalog has no usable profiles")
    return profiles


def selected_profiles(catalog: dict[str, Any], selection: str) -> list[dict[str, Any]]:
    profiles = profiles_by_name(catalog)
    requested = [part.strip() for part in str(selection or "").split(",") if part.strip()]
    if not requested or requested == ["all"]:
        return list(profiles.values())
    missing = [name for name in requested if name not in profiles]
    if missing:
        raise SystemExit(f"unknown profile(s): {', '.join(missing)}")
    return [profiles[name] for name in requested]


def run_command(args: list[str]) -> None:
    print(f"+ {' '.join(args)}", flush=True)
    subprocess.run(args, check=True)


def main() -> int:
    args = parse_args()
    if args.sync_active or args.active_profile:
        print("Legacy active-profile sync flags are ignored; activate candidates through Model Registry.", flush=True)
    root_dir = Path.cwd()
    catalog_path = root_dir / args.catalog_path
    catalog = read_catalog(catalog_path)
    profiles = selected_profiles(catalog, args.profiles)
    data_dir = Path(args.data_dir)
    inference_path = Path(args.inference_path)

    for profile in profiles:
        profile_name = str(profile["name"])
        profile_root = data_dir / "model_profiles" / profile_name
        feature_path = profile_root / "ml_features_ready.parquet"
        model_dir = profile_root / "models"
        profile_root.mkdir(parents=True, exist_ok=True)
        model_dir.mkdir(parents=True, exist_ok=True)

        print(f"Training profile {profile_name}", flush=True)
        run_command(
            [
                sys.executable,
                "feature_engineering.py",
                "--data-dir",
                str(data_dir),
                "--output",
                str(feature_path),
                "--limit",
                "0",
                "--label-threshold",
                str(profile.get("label_threshold", 0.02)),
                "--label-horizon",
                str(profile.get("label_horizon", 5)),
                "--return-mode",
                str(profile.get("return_mode", "close_to_close")),
                "--profile-name",
                profile_name,
            ]
        )
        train_command = [
                sys.executable,
                "train_lightgbm.py",
                "--train-path",
                str(feature_path),
                "--inference-path",
                str(inference_path),
                "--model-dir",
                str(model_dir),
                "--valid-days",
                str(profile.get("valid_days", 60)),
                "--threshold",
                str(profile.get("score_threshold", 0.5)),
                "--top-k",
                str(profile.get("score_top_k", 20)),
                "--objective",
                str(profile.get("model_objective", "binary")),
            ]
        if bool(profile.get("cross_sectional_target", False)):
            train_command.append("--cross-sectional-target")
        run_command(train_command)
        snapshot = create_model_registry_snapshot(data_dir=data_dir, profile=profile_name, market="CN")
        print(
            f"registered immutable candidate {snapshot['model_version']} at {snapshot['artifact_path']}",
            flush=True,
        )

    print("Profile training completed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
