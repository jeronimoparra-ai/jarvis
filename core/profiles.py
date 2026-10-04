#!/usr/bin/env python3
"""
Perfiles de máquina: overlay de config según hardware.

- Detecta laptop si hay batería en /sys/class/power_supply
  (override con JARVIS_PROFILE=laptop|desktop).
- deep_merge del overlay (config.d/<perfil>.yaml) sobre la config.
"""

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def detect_profile() -> str:
    """'laptop' si hay batería, si no 'desktop'. Override: JARVIS_PROFILE."""
    override = os.getenv("JARVIS_PROFILE", "").strip().lower()
    if override in ("laptop", "desktop"):
        return override
    supply = Path("/sys/class/power_supply")
    try:
        for entry in supply.iterdir():
            if entry.name.startswith("BAT"):
                return "laptop"
    except OSError:
        pass
    return "desktop"


def deep_merge(base: dict, overlay: dict) -> dict:
    """Merge recursivo: overlay gana; dicts se fusionan, resto se reemplaza."""
    merged = dict(base)
    for key, value in overlay.items():
        if (key in merged and isinstance(merged[key], dict)
                and isinstance(value, dict)):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_profile_overlay(profile: str, config_dir: Path) -> dict:
    """Lee config.d/<profile>.yaml; {} si no existe o falla."""
    path = config_dir / "config.d" / f"{profile}.yaml"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("No se pudo leer %s: %s", path, e)
        return {}


def apply_profile_to_config(config, config_dir: Path) -> str:
    """
    Detecta el perfil, fusiona su overlay en config.config y lo devuelve.
    Llamar una vez en main.py al inicio.
    """
    profile = detect_profile()
    overlay = load_profile_overlay(profile, config_dir)
    if overlay:
        config.config = deep_merge(config.config, overlay)
        config._apply_env_overrides()
        logger.info("Perfil '%s' aplicado desde config.d/%s.yaml", profile, profile)
    else:
        logger.info("Perfil '%s' (sin overlay).", profile)
    return profile
