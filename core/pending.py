#!/usr/bin/env python3
"""
Confirmación por voz con estado pendiente.

Una sola acción pendiente a la vez. El usuario confirma con
"confirma / sí / ok / vale" o cancela con "cancela / no / abortar".
Si expira el timeout se limpia en silencio.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

CONFIRM_WORDS = ("confirma", "confirmo", "confirmado", "sí", "si", "ok",
                 "vale", "de acuerdo", "adelante", "hazlo")
CANCEL_WORDS = ("cancela", "cancelar", "cancelado", "no", "abortar",
                "aborta", "olvídalo", "olvidalo", "para")

DeferredFn = Callable[[], Awaitable[Dict[str, Any]]]


@dataclass
class PendingAction:
    """Acción de alto riesgo esperando confirmación por voz."""
    description: str
    deferred: DeferredFn
    created_at: float = field(default_factory=time.time)
    timeout_seconds: float = 12.0

    def expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) - self.created_at > self.timeout_seconds


def _normalize(text: str) -> str:
    text = text.lower().strip(" .,!?¿¡:")
    return re.sub(r"\s+", " ", text)


def classify_reply(text: str) -> str:
    """'confirm' | 'cancel' | 'other' para una frase corta de respuesta."""
    norm = _normalize(text)
    # Solo el primer segmento ("sí, confirma" -> "sí")
    first = norm.split(",")[0].strip().split(" ")[0]
    candidates = {norm, first}
    if candidates & set(CONFIRM_WORDS):
        return "confirm"
    if candidates & set(CANCEL_WORDS):
        return "cancel"
    return "other"


class PendingManager:
    """Guarda como máximo una acción pendiente con timeout."""

    def __init__(self, timeout_seconds: float = 12.0):
        self.timeout_seconds = timeout_seconds
        self._pending: Optional[PendingAction] = None
        self._lock = asyncio.Lock()

    async def set(self, description: str, deferred: DeferredFn,
                  timeout: Optional[float] = None) -> None:
        async with self._lock:
            self._pending = PendingAction(
                description=description,
                deferred=deferred,
                timeout_seconds=timeout or self.timeout_seconds)
            logger.info("Pending registrado: %s", description)

    async def peek(self) -> Optional[PendingAction]:
        """Devuelve el pending vigente o None (limpia expirados en silencio)."""
        async with self._lock:
            if self._pending is None:
                return None
            if self._pending.expired():
                logger.info("Pending expirado en silencio: %s",
                            self._pending.description)
                self._pending = None
                return None
            return self._pending

    async def take(self) -> Optional[PendingAction]:
        """Consume y devuelve el pending vigente (o None)."""
        pending = await self.peek()
        if pending is None:
            return None
        async with self._lock:
            self._pending = None
        return pending

    async def clear(self) -> None:
        async with self._lock:
            self._pending = None

    async def handle_reply(self, text: str) -> Optional[str]:
        """
        Si hay pending vigente, interpreta la frase como respuesta.

        Returns:
            str respuesta para hablar, o None si no había pending.
        """
        pending = await self.peek()
        if pending is None:
            return None
        verdict = classify_reply(text)
        if verdict == "confirm":
            action = await self.take()
            if action is None:  # expiró entre peek y take
                return None
            logger.info("Pending confirmado: %s", action.description)
            try:
                result = await action.deferred()
            except Exception as e:
                logger.exception("Deferred falló: %s", e)
                return "Error al ejecutar la acción confirmada."
            if not isinstance(result, dict):
                return ""
            if result.get("silent", False):
                return ""
            return str(result.get("response", "Hecho."))
        if verdict == "cancel":
            await self.clear()
            logger.info("Pending cancelado: %s", pending.description)
            return "Cancelado."
        # Otra frase: recordar y mantener el pending
        return (f"Sigues teniendo pendiente: {pending.description}. "
                "Di confirma o cancela.")
