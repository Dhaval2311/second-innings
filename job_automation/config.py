from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found: {config_path}\n"
            f"Run: python -m job_automation setup\n"
            f"Or copy config.example.yaml to config.yaml and edit it."
        )
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_output_paths(config: dict[str, Any], base_dir: Path) -> tuple[Path, Path]:
    output = config.get("output", {})
    out_dir = (base_dir / output.get("dir", "outputs")).resolve()
    tracker = out_dir / output.get("tracker_file", "job_tracker.csv")
    shortlist = out_dir / output.get("shortlist_file", "job_shortlist.md")
    out_dir.mkdir(parents=True, exist_ok=True)
    return tracker, shortlist


def resolve_db_path(config: dict[str, Any], base_dir: Path) -> Path:
    """Return absolute path to second_innings.db."""
    output = config.get("output", {})
    out_dir = (base_dir / output.get("dir", "outputs")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "second_innings.db"


def get_fresh_only_days(config: dict[str, Any]) -> int:
    return int(config.get("scraper", {}).get("fresh_only_days", 7))


def validate_config(config: dict[str, Any]) -> list[str]:
    """Return list of validation warnings (not errors — app still runs)."""
    warnings: list[str] = []
    profile = config.get("profile", {})
    if not profile.get("full_name"):
        warnings.append("profile.full_name is empty")
    if not profile.get("email"):
        warnings.append("profile.email is empty")
    if not profile.get("resume_path"):
        warnings.append("profile.resume_path is empty — resume upload will be skipped")
    else:
        rp = Path(str(profile["resume_path"])).expanduser()
        if not rp.exists():
            warnings.append(f"profile.resume_path not found: {rp}")

    ai_cfg = config.get("ai", {}) or {}
    provider = ai_cfg.get("provider", "none")
    if provider not in ("none", "gemini_free", "groq"):
        warnings.append(f"ai.provider '{provider}' is not valid. Use: gemini_free | groq | none")
    if provider != "none" and not ai_cfg.get("api_key"):
        warnings.append(f"ai.provider is '{provider}' but ai.api_key is not set — AI disabled")

    return warnings