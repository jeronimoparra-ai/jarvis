#!/usr/bin/env python3
"""
Interruptor del modo chatbot.

- "modo chat" / "hablemos" / "conversemos" -> activa (ChatSession)
- "modo tareas" / "salir del chat" -> desactiva y vuelve a tareas

La sesión la posee el Router; la skill la conmuta vía clase.
"""

from typing import Any, Dict, Optional

from skills.base import Skill


class ChatSkill(Skill):
    """Activa/desactiva la conversación con Jarvis."""

    patterns = [
        "modo chat", "hablemos", "conversemos", "hablemos un rato",
        "modo conversación", "modo conversacion",
        "modo tareas", "salir del chat", "terminar chat",
        "volver a tareas", "modo comandos",
    ]

    intent = "chat"
    llm_enabled = False

    # Inyectado en main.py (y gui_server.py): el ChatSession del Router
    session = None

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from core.chat import ChatSession
        if self.session is None:
            self.session = ChatSession()
        low = text.lower()
        if ChatSession.is_exit(low):
            return {"response": self.session.exit(), "silent": False,
                    "no_audit": True}
        return {"response": self.session.enter(), "silent": False,
                "no_audit": True}
