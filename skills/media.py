#!/usr/bin/env python3
"""
Control multimedia para Jarvis (vía playerctl).

- "pausa la música" / "pausa" -> playerctl pause (silencioso)
- "reproduce / sigue la música" -> playerctl play
- "siguiente canción" / "anterior canción" -> next / previous
- "qué está sonando" -> artista - título

Sin playerctl instalado: responde cómo instalarlo.
"""

import asyncio
import logging
import shutil
from typing import Dict, Any, Optional

from skills.base import Skill

logger = logging.getLogger(__name__)


class MediaSkill(Skill):
    """Control de reproducción multimedia."""

    patterns = [
        "pausa la música", "pausa", "reproduce", "sigue la música", "continúa",
        "siguiente canción", "siguiente", "anterior canción", "anterior",
        "qué está sonando", "que está sonando", "qué suena", "sube la música",
    ]

    intent = "media"

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if shutil.which("playerctl") is None:
            return {"response": "Instala playerctl para control multimedia.",
                    "silent": False}
        low = text.lower()
        if "siguiente" in low:
            await self._run("next")
            return {"response": "", "silent": True}
        if "anterior" in low:
            await self._run("previous")
            return {"response": "", "silent": True}
        if "pausa" in low:
            await self._run("pause")
            return {"response": "", "silent": True}
        if "sonando" in low or "suena" in low:
            info = await self._run("metadata --format '{{artist}} - {{title}}'")
            info = info.strip() or "Nada en reproducción."
            return {"response": info[:200], "silent": False}
        # reproduce / sigue / resto -> play
        await self._run("play")
        return {"response": "", "silent": True}

    async def _run(self, args: str) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                f"playerctl {args}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return out.decode(errors="replace").strip()
        except Exception as e:
            logger.debug("playerctl falló: %s", e)
            return ""
