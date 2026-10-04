#!/usr/bin/env python3
"""
Audit log + deshacer.

- JSONL en ~/.local/share/jarvis/audit.log: ts, skill, text, action,
  result, reversible, undo_payload.
- Stack de undo (máx. 20) solo para acciones reversible=True.
- register_undo(type, handler) + undo_last().
"""

import json
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

UndoHandler = Callable[[Dict[str, Any]], Awaitable[str]]
MAX_UNDO = 20


@dataclass
class AuditEntry:
    ts: float
    skill: str
    text: str
    action: str
    result: str = ""
    reversible: bool = False
    undo_payload: Dict[str, Any] = field(default_factory=dict)


class AuditLog:
    """Log persistente de acciones + pila de deshacer."""

    def __init__(self, path: Optional[Path] = None, enabled: bool = True):
        self.enabled = enabled
        self.path = path or (Path.home() / ".local" / "share" / "jarvis" / "audit.log")
        self._undo_handlers: Dict[str, UndoHandler] = {}
        self._undo_stack: Deque[AuditEntry] = deque(maxlen=MAX_UNDO)

    def register_undo(self, undo_type: str, handler: UndoHandler) -> None:
        """Registra cómo deshacer un tipo de undo_payload."""
        self._undo_handlers[undo_type] = handler
        logger.debug("Undo handler registrado: %s", undo_type)

    def log(self, entry: AuditEntry) -> None:
        """Escribe la entrada en disco y apila si es reversible."""
        if entry.reversible and entry.undo_payload.get("type") in self._undo_handlers:
            self._undo_stack.append(entry)
        elif entry.reversible:
            logger.debug("Sin handler para undo type=%s; no se apila.",
                         entry.undo_payload.get("type"))
        if not self.enabled:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("No se pudo escribir audit.log: %s", e)

    def recent(self, n: int = 3) -> List[AuditEntry]:
        """Últimas n entradas (de disco; [] si no hay log)."""
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
            out = []
            for line in lines:
                try:
                    d = json.loads(line)
                    out.append(AuditEntry(**{k: d.get(k, v) for k, v in
                        {"ts": 0.0, "skill": "?", "text": "",
                         "action": "?", "result": "",
                         "reversible": False, "undo_payload": {}}.items()}))
                except (json.JSONDecodeError, TypeError):
                    continue
            return out
        except Exception as e:
            logger.warning("No se pudo leer audit.log: %s", e)
            return []

    async def undo_last(self) -> str:
        """Deshace la última acción reversible. Mensaje breve."""
        while self._undo_stack:
            entry = self._undo_stack.pop()
            handler = self._undo_handlers.get(entry.undo_payload.get("type", ""))
            if handler is None:
                continue
            try:
                detail = await handler(entry.undo_payload)
                self.log(AuditEntry(ts=time.time(), skill="audit",
                                    text=f"deshacer: {entry.action}",
                                    action=f"undo:{entry.action}",
                                    result=detail))
                return f"Deshecho: {entry.action}. {detail}".strip()
            except Exception as e:
                logger.exception("Undo falló: %s", e)
                return "No pude deshacer esa acción."
        return "No hay nada que deshacer."


def relative_time(ts: float, now: Optional[float] = None) -> str:
    """'hace 5 min' para resúmenes hablados."""
    delta = int((now or time.time()) - ts)
    if delta < 10:
        return "ahora mismo"
    if delta < 60:
        return f"hace {delta} segundos"
    mins = delta // 60
    if mins < 60:
        return f"hace {mins} minuto(s)"
    hours = mins // 60
    if hours < 24:
        return f"hace {hours} hora(s)"
    return f"hace {hours // 24} día(s)"
