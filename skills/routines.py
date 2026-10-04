#!/usr/bin/env python3
"""
Rutinas / macros deterministas (sin LLM), definidas en config.yaml.

Cada rutina: triggers (frases) + steps (acciones). Pasos en secuencia
rápida (150 ms); un fallo no detiene el resto. Silencio si todo ok.

Config (config.yaml) manda; defaults en código como respaldo.
El SkillManager/config se inyecta vía RoutinesSkill.config y .manager.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from core.platform import IS_WINDOWS, PlatformOps
from skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_ROUTINES: Dict[str, Dict[str, Any]] = {
    "modo_trabajo": {
        "triggers": ["modo trabajo", "modo office"],
        "steps": [
            {"action": "volume", "percent": 30},
            {"action": "open_app", "app": "code"},
            {"action": "open_app", "app": "terminal"},
            {"action": "notify", "message": "Modo trabajo"},
        ],
    },
    "modo_fiesta": {
        "triggers": ["modo fiesta", "activar fiesta", "fiesta"],
        "steps": [
            {"action": "play_youtube", "query": "lo-fi hip hop radio"},
            {"action": "open_app", "app": "code"},
            {"action": "volume", "percent": 60},
        ],
    },
    "cancion_favorita": {
        "triggers": ["pon mi canción", "pon mi cancion", "mi canción de youtube",
                     "mi cancion de youtube", "pon música", "pon musica"],
        "steps": [
            {"action": "open_url",
             "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            {"action": "volume", "percent": 65},
        ],
    },
    "modo_foco": {
        "triggers": ["modo foco", "modo concentracion", "modo concentración"],
        "steps": [
            {"action": "volume", "percent": 20},
            {"action": "notify", "message": "Modo foco: sin ruido"},
        ],
    },
    "cierre": {
        "triggers": ["cierre del día", "cierre del dia"],
        "steps": [
            {"action": "media_pause"},
            {"action": "screenshot"},
            {"action": "lock"},
            {"action": "notify", "message": "Cierre del día"},
        ],
    },
    "modo_noche": {
        "triggers": ["modo noche"],
        "steps": [
            {"action": "volume", "percent": 15},
            {"action": "brightness", "percent": 20},
            {"action": "notify", "message": "Modo noche"},
        ],
    },
}


class RoutinesSkill(Skill):
    """Ejecuta macros multi-paso definidas en config."""

    patterns = [
        "modo", "rutina", "rutinas", "qué rutinas hay", "que rutinas hay",
        "fiesta", "pon mi", "mi canción", "mi cancion", "cierre del día",
    ]

    intent = "routines"

    # Inyectados en main.py (y gui_server.py)
    config = None
    manager = None

    # --- resolución ------------------------------------------------------

    def _routines(self) -> Dict[str, Dict[str, Any]]:
        merged = dict(DEFAULT_ROUTINES)
        try:
            cfg = self.config.get("routines", {}) if self.config else {}
        except Exception:
            cfg = {}
        for name, routine in (cfg or {}).items():
            if isinstance(routine, dict):
                merged[str(name)] = routine
        return merged

    def _app_name(self, logical: str) -> str:
        """Mapea nombre lógico -> real según SO (apps_map de config)."""
        try:
            table = (self.config.get("apps_map", {}) if self.config else {}) or {}
        except Exception:
            table = {}
        os_key = "windows" if IS_WINDOWS else "linux"
        mapped = (table.get(os_key, {}) or {}).get(logical)
        return str(mapped or logical)

    def _match(self, low: str) -> Optional[str]:
        for name, routine in self._routines().items():
            for trigger in routine.get("triggers", []):
                if str(trigger).lower() in low:
                    return name
        return None

    # --- ejecución --------------------------------------------------------

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        low = text.lower()
        name = self._match(low)
        if name is None:
            names = ", ".join(sorted(self._routines()))
            return {"response": f"Rutinas: {names}.", "silent": False,
                    "no_audit": True}
        return await self._run_named(name)

    async def _run_named(self, name: str) -> Dict[str, Any]:
        routine = self._routines().get(name)
        if not routine:
            return {"response": f"No existe la rutina {name}.", "silent": False}
        steps: List[Dict[str, Any]] = routine.get("steps", [])
        ok = 0
        for step in steps:
            try:
                if await self._do_step(step):
                    ok += 1
                else:
                    logger.debug("Paso fallido en '%s': %s", name, step)
            except Exception as e:
                logger.debug("Paso '%s' error: %s", name, e)
            await asyncio.sleep(0.15)
        if ok == len(steps):
            return {"response": "", "silent": True,
                    "audit_action": f"routine:{name}"}
        return {"response": f"Rutina {name}: {ok} de {len(steps)} pasos.",
                "silent": False, "audit_action": f"routine:{name}"}

    async def _do_step(self, step: Dict[str, Any]) -> bool:
        action = str(step.get("action", ""))
        if action == "open_url":
            return await PlatformOps.open_url(str(step.get("url", "")))
        if action == "open_app":
            return await PlatformOps.open_app(self._app_name(str(step.get("app", ""))))
        if action == "volume":
            pct = step.get("percent")
            if pct is None:
                return False
            return await PlatformOps.set_volume(percent=int(pct))
        if action == "notify":
            return await PlatformOps.notify("Jarvis", str(step.get("message", "")))
        if action == "play_youtube":
            from skills.media import (assist_youtube_play, build_youtube_url,
                                      detect_provider, search_ytmusic,
                                      youtube_load_wait)
            url = str(step.get("url") or "")
            provider = str(step.get("provider") or "").lower()
            if not provider:
                try:
                    provider = str(((self.config.get("media", {}) or {}).get(
                        "default_provider", "youtube"))) if self.config else "youtube"
                except Exception:
                    provider = "youtube"
            if not url:
                query = str(step.get("query", "")).strip()
                if not query:
                    return False
                if provider == "ytmusic":
                    vid, _ = await search_ytmusic(query)
                    if vid:
                        url = f"https://music.youtube.com/watch?v={vid}"
                    else:
                        provider = "youtube"  # fallback sin red/librería
                if provider != "ytmusic":
                    url = build_youtube_url(query)
            is_search = "search_query" in url
            if not await PlatformOps.open_url(url):
                return False
            if provider == "ytmusic" and not is_search:
                return True  # el watch auto-reproduce, nada más que hacer
            await asyncio.sleep(youtube_load_wait(self.config))
            await assist_youtube_play(url, self.config, is_search=is_search)
            return True
        if action == "lock":
            return await PlatformOps.lock_session()
        if action == "screenshot":
            from datetime import datetime
            from pathlib import Path
            dest = Path.home() / ("Pictures" if IS_WINDOWS else "Imágenes")
            path = dest / f"jarvis-{datetime.now():%Y%m%d-%H%M%S}.png"
            return await PlatformOps.screenshot(str(path))
        if action == "brightness":
            if IS_WINDOWS or self.manager is None:
                return False
            system = self.manager.get_skill("system")
            if system is None or not hasattr(system, "_run_command"):
                return False
            import shutil
            if shutil.which("brightnessctl") is None:
                return False
            result = await system._run_command(
                f"brightnessctl set {int(step.get('percent', 20))}%")
            return result.returncode == 0
        if action == "media_pause":
            mgr = self.manager
            if mgr is not None:
                media = mgr.get_skill("media")
                if media is not None:
                    res = await media.execute("pausa la música")
                    return isinstance(res, dict)
            if not IS_WINDOWS:
                import shutil
                if shutil.which("playerctl"):
                    from utils.safe_subprocess import run_exec
                    rc, _, _ = await run_exec(["playerctl", "pause"],
                                              timeout=5.0)
                    return rc == 0
            return False
        if action == "wait":
            await asyncio.sleep(float(step.get("seconds", 1)))
            return True
        logger.warning("Acción de rutina desconocida: %s", action)
        return False
