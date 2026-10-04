#!/usr/bin/env python3
"""
Modo chatbot: conversación breve con Jarvis (opcional).

"modo chat" / "hablemos" lo activa; "modo tareas" / "salir del chat"
lo apaga. En modo chat todo va al LLM con historial corto
(task-oriented sigue siendo el modo por defecto).
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

MAX_TURNS = 10  # últimos intercambios que se recuerdan

EXIT_PHRASES = ("modo tareas", "salir del chat", "terminar chat",
                "volver a tareas", "modo comandos")


class ChatSession:
    """Estado de conversación (una sesión por proceso)."""

    def __init__(self):
        self.active = False
        self.history: List[Dict[str, str]] = []

    def enter(self) -> str:
        self.active = True
        self.history.clear()
        logger.info("Modo chat activado.")
        return "Modo chat. Hablemos; di modo tareas para volver."

    def exit(self) -> str:
        self.active = False
        self.history.clear()
        logger.info("Modo chat desactivado.")
        return "De vuelta a tareas. Dime la orden."

    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        self.history = self.history[-(MAX_TURNS * 2):]

    @staticmethod
    def is_exit(text: str) -> bool:
        low = text.lower().strip()
        return any(p in low for p in EXIT_PHRASES)
