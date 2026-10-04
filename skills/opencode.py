#!/usr/bin/env python3
"""
Bridge OpenCode: lanza el agente en un repo (no autónomo, solo lanza).

- "abre opencode" -> abre la GUI/terminal de opencode si existe
- "revisa este repo" / "opencode aquí" -> detecta git root del cwd y lo lanza ahí

Busca el binario en PATH y en ~/.opencode/bin. Silencio al éxito.
"""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from skills.base import Skill

logger = logging.getLogger(__name__)


class OpencodeSkill(Skill):
    """Abre OpenCode en el repo actual."""

    patterns = [
        "abre opencode", "abrir opencode", "opencode",
        "revisa este repo", "revisa el repo", "opencode aquí", "opencode aqui",
    ]

    intent = "opencode"

    @staticmethod
    def find_binary() -> Optional[str]:
        """Ruta del binario o None."""
        found = shutil.which("opencode")
        if found:
            return found
        for candidate in (Path.home() / ".opencode" / "bin" / "opencode",
                          Path.home() / ".local" / "bin" / "opencode"):
            if candidate.is_file():
                return str(candidate)
        return None

    @staticmethod
    def find_git_root(start: Optional[Path] = None) -> Optional[Path]:
        """Sube desde cwd buscando .git."""
        current = (start or Path.cwd()).resolve()
        for parent in [current, *current.parents]:
            if (parent / ".git").exists():
                return parent
        return None

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        binary = self.find_binary()
        if binary is None:
            return {"response": "OpenCode no está instalado (ni en PATH ni en ~/.opencode/bin).",
                    "silent": False}
        low = text.lower()
        cwd = str(self.find_git_root() or Path.cwd())
        if "revisa" in low or "aquí" in low or "aqui" in low:
            logger.info("OpenCode lanzado en %s", cwd)
        try:
            await asyncio.create_subprocess_exec(
                binary, cwd=cwd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            return {"response": "", "silent": True}
        except Exception as e:
            logger.error("No se pudo lanzar opencode: %s", e)
            return {"response": "No pude lanzar OpenCode.", "silent": False}
