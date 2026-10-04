#!/usr/bin/env python3
"""
Dictado al portapapeles para Jarvis.

- "dicta <texto>" / "copia esto <texto>" -> portapapeles (wl-copy/xclip/xsel)
- "escribe <texto>" / "pega" -> además Ctrl+V en la ventana enfocada (xdotool)

Respuestas: "En el portapapeles." / "Escrito."
"""

import logging
import re
from typing import Any, Dict, Optional

from skills.base import Skill

logger = logging.getLogger(__name__)


class DictationSkill(Skill):
    """Manda texto dictado al portapapeles (y opcionalmente lo escribe)."""

    patterns = [
        "dicta", "dictado", "copia esto", "copia", "escribe", "pega",
    ]

    intent = "dictation"

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        low = text.lower().strip()
        payload = self.extract_payload(text)
        if not payload:
            return {"response": "¿Qué texto? Di por ejemplo: dicta compra leche.",
                    "silent": False}
        if not await self._to_clipboard(payload):
            return {"response": "No hay portapapeles (falta wl-copy o xclip).",
                    "silent": False}
        if low.startswith(("escribe", "pega")):
            if await self._paste():
                return {"response": "Escrito.", "silent": False}
            return {"response": "En el portapapeles (sin xdotool no puedo pegarlo).",
                    "silent": False}
        return {"response": "En el portapapeles.", "silent": True}

    _KEYWORDS = ("dicta", "dictado", "escribe", "pega", "pon",
                 "copia", "copia esto")

    @staticmethod
    def extract_payload(text: str) -> str:
        """Texto tras dicta/escribe/copia esto/pega ('' si solo vino la orden)."""
        cleaned = re.sub(r"^(dicta(?:do)?|escribe|pega|pon)\s+", "",
                         text.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"^copia(?:\s+esto)?\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" ,.")
        if cleaned.lower() in DictationSkill._KEYWORDS:
            return ""
        return cleaned

    async def _to_clipboard(self, payload: str) -> bool:
        """Copia vía PlatformOps (wl-copy/xclip/PowerShell/clip)."""
        from core.platform import PlatformOps
        return await PlatformOps.copy_to_clipboard(payload)

    async def _paste(self) -> bool:
        """Ctrl+V en la ventana enfocada (vía PlatformOps)."""
        from core.platform import PlatformOps
        return await PlatformOps.paste_hotkey()
