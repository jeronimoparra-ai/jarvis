#!/usr/bin/env python3
"""
Skill de hora y fecha para Jarvis.

- "qué hora es" / "dime la hora" -> "Son las 18:25."
- "qué fecha es" / "qué día es hoy" -> "Hoy es sábado 3 de octubre de 2026."
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from skills.base import Skill

logger = logging.getLogger(__name__)

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
          "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


class ClockSkill(Skill):
    """Hora y fecha actuales."""

    patterns = [
        "qué hora es", "que hora es", "dime la hora", "la hora",
        "qué fecha es", "que fecha es", "qué día es hoy", "que día es hoy",
        "qué día es", "que día es",
    ]

    intent = "clock"

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now = datetime.now()
        low = text.lower()
        if "hora" in low:
            return {"response": f"Son las {now.hour}:{now.minute:02d}.", "silent": False}
        dia = _DIAS[now.weekday()]
        mes = _MESES[now.month]
        return {"response": f"Hoy es {dia} {now.day} de {mes} de {now.year}.",
                "silent": False}
