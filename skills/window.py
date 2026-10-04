#!/usr/bin/env python3
"""
Control de la ventana activa para Jarvis.

- "cierra esto" / "cierra esta ventana" -> cierra la enfocada (silencio)
- "qué ventana" / "ventana activa" / "en qué estoy" -> informa título
- "captura esta ventana" / "pantallazo de esta ventana" -> captura solo ella
"""

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.window_context import get_active_window
from skills.base import Skill

logger = logging.getLogger(__name__)


class WindowSkill(Skill):
    """Opera sobre la ventana con foco."""

    patterns = [
        "cierra esto", "cierra esta ventana", "cerrar esto",
        "qué ventana", "que ventana", "ventana activa", "en qué estoy",
        "en que estoy", "dónde estoy", "donde estoy",
        "captura esta ventana", "pantallazo de esta ventana",
        "captura la ventana",
    ]

    intent = "window"

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        low = text.lower()
        if "captura" in low or "pantallazo" in low:
            return await self._capture_window()
        if "cierra" in low or "cerrar" in low or "cierra esto" in low:
            from core.platform import PlatformOps
            ok = await PlatformOps.close_active_window()
            if ok:
                return {"response": "", "silent": True}
            return {"response": "No pude cerrar la ventana activa.",
                    "silent": False}
        info = await get_active_window()
        if info is None or not (info.title or info.wm_class):
            return {"response": "No veo ninguna ventana activa.",
                    "silent": False}
        label = info.title or info.wm_class
        return {"response": f"Estás en: {label[:120]}.", "silent": False}

    async def _capture_window(self) -> Dict[str, Any]:
        """Captura solo la ventana activa (gnome-screenshot -w)."""
        if shutil.which("gnome-screenshot") is None:
            return {"response": "Instala gnome-screenshot para capturas.",
                    "silent": False}
        dest = Path.home() / "Imágenes"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"jarvis-ventana-{datetime.now():%Y%m%d-%H%M%S}.png"
        from utils.safe_subprocess import run_exec
        rc, _, _ = await run_exec(
            ["gnome-screenshot", "-w", "-f", str(path)], timeout=15.0)
        if rc == 0:
            return {"response": "", "silent": True}
        return {"response": "No se pudo capturar la ventana.", "silent": False}
