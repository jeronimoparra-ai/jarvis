#!/usr/bin/env python3
"""
Rutinas / macros deterministas (sin LLM).

- "modo trabajo": volumen 30%, abrir code + terminal si existen, notify
- "modo foco": volumen 20%, notify
- "cierre del día": pausar media, captura, bloquear sesión, notify
- "modo noche": volumen 15%, brillo 20%, notify
- "rutina" sin nombre: lista las disponibles

Pasos encadenados con pequeños delays; un paso fallido no rompe el flujo.
El SkillManager se inyecta vía RoutinesSkill.manager (main.py).
"""

import asyncio
import logging
import shutil
from typing import Any, Dict, List, Optional, Tuple

from skills.base import Skill

logger = logging.getLogger(__name__)


class RoutinesSkill(Skill):
    """Ejecuta macros de varios pasos."""

    patterns = [
        "modo trabajo", "modo foco", "modo concentracion", "modo concentración",
        "cierre del día", "cierre del dia", "modo noche", "rutina", "rutinas",
    ]

    intent = "routines"

    # Inyectado en main.py (y gui_server.py)
    manager = None

    ROUTINES = ("trabajo", "foco", "cierre", "noche")

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        low = text.lower()
        name = self._which(low)
        if name is None:
            return {"response": "Rutinas: modo trabajo, modo foco, cierre del día, modo noche.",
                    "silent": False, "no_audit": True}
        ok, total = await self._run(name)
        summary = f"Rutina {name}: {ok} de {total} pasos listos."
        return {"response": summary, "silent": False,
                "audit_action": f"routine:{name}"}

    @classmethod
    def _which(cls, low: str) -> Optional[str]:
        if "trabajo" in low:
            return "trabajo"
        if "foco" in low or "concentra" in low:
            return "foco"
        if "cierre" in low:
            return "cierre"
        if "noche" in low:
            return "noche"
        return None

    async def _run(self, name: str) -> Tuple[int, int]:
        steps = {
            "trabajo": [self._step_volume(30), self._step_open("code"),
                        self._step_open("terminal"), self._step_notify("Modo trabajo")],
            "foco": [self._step_volume(20), self._step_notify("Modo foco: sin ruido")],
            "cierre": [self._step_media_pause, self._step_screenshot,
                       self._step_lock, self._step_notify("Cierre del día")],
            "noche": [self._step_volume(15), self._step_brightness(20),
                      self._step_notify("Modo noche")],
        }[name]
        ok = 0
        for step in steps:
            try:
                if await step():
                    ok += 1
            except Exception as e:
                logger.debug("Paso de rutina '%s' falló: %s", name, e)
            await asyncio.sleep(0.3)
        return ok, len(steps)

    async def _shell(self, cmd: str, timeout: float = 8.0) -> bool:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), timeout=timeout)
            return proc.returncode == 0
        except Exception:
            return False

    def _step_volume(self, percent: int):
        async def _go() -> bool:
            if shutil.which("pactl"):
                return await self._shell(
                    f"pactl set-sink-volume @DEFAULT_SINK@ {percent}%")
            if shutil.which("wpctl"):
                return await self._shell(
                    f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {percent}%")
            return False
        return _go

    def _step_brightness(self, percent: int):
        async def _go() -> bool:
            if shutil.which("brightnessctl"):
                return await self._shell(f"brightnessctl set {percent}%")
            return False
        return _go

    def _step_open(self, app: str):
        async def _go() -> bool:
            mgr = self.manager
            if mgr is None:
                return False
            apps = mgr.get_skill("apps")
            if apps is None:
                return False
            result = await apps.execute(f"abre {app}")
            if not isinstance(result, dict):
                return False
            resp = str(result.get("response", ""))
            # AppsSkill informa el fallo en texto: no contarlo como éxito
            if resp.startswith(("No encontré", "No tengo", "Error", "No reconozco")):
                return False
            return True
        return _go

    async def _step_media_pause(self) -> bool:
        if shutil.which("playerctl"):
            return await self._shell("playerctl pause")
        return False

    async def _step_screenshot(self) -> bool:
        if not shutil.which("gnome-screenshot"):
            return False
        from datetime import datetime
        from pathlib import Path
        dest = Path.home() / "Imágenes"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"jarvis-cierre-{datetime.now():%Y%m%d-%H%M%S}.png"
        return await self._shell(f"gnome-screenshot -f '{path}'")

    async def _step_lock(self) -> bool:
        return await self._shell("loginctl lock-session")

    def _step_notify(self, message: str):
        async def _go() -> bool:
            if shutil.which("notify-send"):
                return await self._shell(f"notify-send Jarvis '{message}'")
            return True  # sin notify igual cuenta como listo
        return _go
