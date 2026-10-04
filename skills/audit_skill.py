#!/usr/bin/env python3
"""
Historial y deshacer para Jarvis.

- "qué hiciste" / "historial" -> resume 3 últimas acciones con tiempo relativo
- "deshaz" / "deshacer" / "deshaz lo último" -> undo_last()

El AuditLog se inyecta vía AuditSkill.audit (main.py). Sin inyección,
el historial funciona leyendo el disco; deshacer necesita la sesión viva.
"""

import logging
from typing import Any, Dict, Optional

from core.audit import AuditLog, relative_time
from skills.base import Skill

logger = logging.getLogger(__name__)


class AuditSkill(Skill):
    """Consulta el historial de acciones y deshace la última reversible."""

    patterns = [
        "qué hiciste", "que hiciste", "historial", "qué has hecho",
        "deshaz", "deshacer", "deshaz lo último", "deshaz lo ultimo",
    ]

    intent = "audit"
    llm_enabled = False  # solo reglas; no tiene sentido vía LLM

    # Inyectado en main.py (y gui_server.py)
    audit: Optional[AuditLog] = None

    def _log(self) -> AuditLog:
        return self.audit or AuditLog()

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        low = text.lower()
        audit = self._log()
        if "deshaz" in low or "deshacer" in low:
            if self.audit is None:
                return {"response": "Deshacer necesita la sesión activa.",
                        "silent": False, "no_audit": True}
            detail = await self.audit.undo_last()
            return {"response": detail, "silent": False, "no_audit": True}
        recent = audit.recent(3)
        if not recent:
            return {"response": "Aún no he hecho nada.", "silent": False,
                    "no_audit": True}
        parts = [f"{e.action} ({relative_time(e.ts)})" for e in recent]
        return {"response": "Último: " + "; ".join(parts) + ".",
                "silent": False, "no_audit": True}
