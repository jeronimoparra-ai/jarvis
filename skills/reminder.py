#!/usr/bin/env python3
"""
Temporizadores y recordatorios para Jarvis.

- "recuérdame en 5 minutos tomar agua"
- "pon un temporizador de 10 minutos"
- "avísame en 30 segundos"

Al cumplirse: notificación de escritorio (notify-send) + callback
de anuncio (la UI o el loop de audio lo conectan para hablarlo).
"""

import asyncio
import logging
import re
import shutil
from typing import Dict, Any, Optional, Callable, Awaitable

from skills.base import Skill

logger = logging.getLogger(__name__)

AnnounceFn = Callable[[str], Awaitable[None]]

_UNITS = {
    "segundo": 1, "segundos": 1, "seg": 1,
    "minuto": 60, "minutos": 60, "min": 60,
    "hora": 3600, "horas": 3600, "h": 3600,
}


class ReminderSkill(Skill):
    """Crea temporizadores en segundo plano."""

    patterns = [
        "recuérdame", "recuerdame", "temporizador", "avísame", "avisame",
        "alarma",
    ]

    intent = "reminder"

    def __init__(self):
        super().__init__()
        self._announce: AnnounceFn = self._default_announce

    def set_announce_callback(self, fn: AnnounceFn) -> None:
        """Conecta el aviso de cumplimiento (p.ej. TTS o evento GUI)."""
        self._announce = fn

    @staticmethod
    async def _default_announce(message: str) -> None:
        logger.info("[Recordatorio] %s", message)

    @staticmethod
    def parse_delay(text: str) -> Optional[int]:
        """Extrae 'en N <unidad>' -> segundos. None si no hay."""
        m = re.search(r"en\s+(\d+)\s*(segundos?|seg|minutos?|min|horas?|h)\b",
                      text.lower())
        if not m:
            m = re.search(r"de\s+(\d+)\s*(segundos?|seg|minutos?|min|horas?|h)\b",
                          text.lower())
        if not m:
            return None
        return int(m.group(1)) * _UNITS[m.group(2)]

    @staticmethod
    def _message_text(text: str) -> str:
        """Quita el prefijo de orden para quedarnos con el mensaje."""
        cleaned = re.sub(r"^(recu[eé]rdame|av[íi]same)\s+(en\s+\d+\s*\w+\s+)?",
                         "", text.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"^(pon\s+(un\s+)?temporizador\s+(de\s+\d+\s*\w+\s*)?)",
                         "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" ,.") or "¡Tiempo cumplido!"

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        delay = self.parse_delay(text)
        if delay is None or delay <= 0:
            return {"response": "Dime en cuánto tiempo: 'en 5 minutos'.",
                    "silent": False}
        if delay > 12 * 3600:
            return {"response": "Máximo 12 horas para un recordatorio.",
                    "silent": False}
        message = self._message_text(text)
        asyncio.get_running_loop().create_task(self._wait_and_fire(delay, message))
        mins = delay // 60
        human = f"{mins} minuto(s)" if delay >= 60 else f"{delay} segundo(s)"
        return {"response": f"Anotado. Te aviso en {human}.", "silent": False}

    async def _wait_and_fire(self, delay: int, message: str) -> None:
        logger.info("Temporizador creado: %ds -> '%s'", delay, message)
        await asyncio.sleep(delay)
        logger.info("Temporizador cumplido: '%s'", message)
        try:
            if shutil.which("notify-send"):
                await asyncio.create_subprocess_exec(
                    "notify-send", "Jarvis", message,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL)
        except Exception as e:
            logger.debug("notify-send falló: %s", e)
        try:
            await self._announce(message)
        except Exception as e:
            logger.error("Callback de recordatorio falló: %s", e)
