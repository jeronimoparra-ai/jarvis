#!/usr/bin/env python3
"""
Multimedia para Jarvis: playerctl local + YouTube real.

playerctl (si existe):
- "pausa la música" / "siguiente canción" / "qué está sonando" ...

YouTube (siempre disponible con navegador):
- "abre youtube" -> solo abre youtube.com (sin play)
- "pon bohemian rhapsody" / "reproduce X en youtube" / "play X" ->
  search URL + intento de reproducir (best-effort con teclado).

Autoplay: los navegadores pueden bloquearlo; el plan B es enviar
Down+Return (resultados) o "k" (página de video) vía input_control.
Sin xdotool: se abre la búsqueda y se avisa.
"""

import asyncio
import logging
import re
import shutil
import urllib.parse
from typing import Dict, Any, Optional

from core.platform import PlatformOps
from skills.base import Skill

logger = logging.getLogger(__name__)

YOUTUBE_HOME = "https://www.youtube.com"
YOUTUBE_WATCH_RE = re.compile(r"(?:youtube\.com/watch\?|youtu\.be/)")


def build_youtube_url(query_or_url: str) -> str:
    """URL completa tal cual, o search URL con query urlencoded."""
    text = query_or_url.strip()
    if YOUTUBE_WATCH_RE.search(text):
        return text if text.startswith("http") else f"https://{text}"
    m = re.search(r"https?://[^\s,;]+", text)
    if m:
        return m.group(0)
    return ("https://www.youtube.com/results?search_query="
            + urllib.parse.quote_plus(text))


def extract_play_query(text: str) -> str:
    """'pon bohemian rhapsody en youtube' -> 'bohemian rhapsody'."""
    cleaned = text.strip()
    cleaned = re.sub(r"^(quiero|quisiera|me gustaria|me gustaría)\s+",
                     "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(pon|reproduce|reproducir|play|escucha|escuchar)\s+",
                     "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(en|de)\s+(youtube|spotify)\s*$", "",
                     cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(la\s+|el\s+)?(canci[oó]n|tema|video|vídeo)\s+",
                     "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,.")


def wants_youtube_play(text: str) -> bool:
    """True si pide REPRODUCIR (no solo abrir)."""
    low = text.lower()
    if re.search(r"https?://|youtu\.be|watch\?v=", low):
        return True
    if "youtube" in low and ("abre" in low or "abrir" in low) \
            and not re.search(r"\b(pon|play|reproduce|escucha)\b", low):
        return False  # "abre youtube" = solo abrir
    return bool(re.search(r"\b(pon|play|reproduce|reproducir|escucha)\b", low))


async def assist_youtube_play(url: str, config=None,
                              is_search: bool = True) -> bool:
    """
    Best-effort post-apertura: enfoca el navegador y pulsa teclas.
    Search -> Down+Return (primer resultado). Watch -> "k" (play).
    Devuelve True si pudo intentarlo (backend disponible).
    """
    from core.input_control import InputControl
    from core.window_context import focus_window_by_class
    ctl = InputControl(config)
    if ctl.backend() is None:
        logger.info("Sin backend de teclado (xdotool): solo se abrió la URL.")
        return False
    # Enfocar navegador (best-effort, no bloquea si falla)
    for cls in ("firefox", "chrome", "chromium", "brave"):
        try:
            if await focus_window_by_class(cls):
                break
        except Exception:
            continue
    await asyncio.sleep(0.5)
    if is_search:
        ok = await ctl.press("Down") and await ctl.press("Return")
    else:
        ok = await ctl.press("k")
        if not ok:
            ok = await ctl.press("space")
    return ok


def youtube_load_wait(config=None, default: float = 3.5) -> float:
    try:
        return float((config.get("media", {}) or {}).get(
            "youtube_load_wait_s", default)) if config else default
    except Exception:
        return default


class MediaSkill(Skill):
    """Control multimedia local + reproducción YouTube."""

    patterns = [
        "pausa la música", "pausa", "reproduce", "sigue la música", "continúa",
        "siguiente canción", "siguiente", "anterior canción", "anterior",
        "qué está sonando", "que está sonando", "qué suena", "sube la música",
        "pon", "play", "escucha", "en youtube", "abre youtube", "youtube",
    ]

    intent = "media"

    # Inyectado en main.py (y gui_server.py)
    config = None

    def _wait(self) -> float:
        return youtube_load_wait(self.config)

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from core.nlu import canonicalize
        low = canonicalize(text)
        # "abre youtube" sin verbo de reproducción -> solo abrir el sitio
        if "youtube" in low and not wants_youtube_play(low):
            ok = await PlatformOps.open_url(YOUTUBE_HOME)
            if ok:
                return {"response": "", "silent": True}
            return {"response": "No pude abrir YouTube.", "silent": False}
        # "pon X" / URL / "reproduce X en youtube" -> buscar + reproducir
        if wants_youtube_play(low):
            query = extract_play_query(low)
            if not query:
                ok = await PlatformOps.open_url(YOUTUBE_HOME)
                return {"response": "", "silent": True} if ok else \
                    {"response": "¿Qué pongo?", "silent": False}
            return await self._play_youtube(query)
        # Resto: playerctl local
        if shutil.which("playerctl") is None:
            return {"response": "Instala playerctl para control multimedia.",
                    "silent": False}
        if "siguiente" in low:
            await self._run("next")
            return {"response": "", "silent": True}
        if "anterior" in low:
            await self._run("previous")
            return {"response": "", "silent": True}
        if "pausa" in low:
            await self._run("pause")
            return {"response": "", "silent": True}
        if "sonando" in low or "suena" in low:
            info = await self._run("metadata --format '{{artist}} - {{title}}'")
            info = info.strip() or "Nada en reproducción."
            return {"response": info[:200], "silent": False}
        await self._run("play")
        return {"response": "", "silent": True}

    async def _play_youtube(self, query: str) -> Dict[str, Any]:
        url = build_youtube_url(query)
        is_search = "search_query" in url
        if not await PlatformOps.open_url(url):
            return {"response": "No pude abrir el navegador.", "silent": False}
        await asyncio.sleep(self._wait())
        tried = await assist_youtube_play(url, self.config, is_search=is_search)
        if tried:
            return {"response": "", "silent": True,
                    "audit_action": f"media:play {query[:60]}"}
        return {"response": f"Busqué {query} en YouTube (sin xdotool no puedo darle play).",
                "silent": False, "audit_action": f"media:search {query[:60]}"}

    async def _run(self, args: str) -> str:
        from utils.safe_subprocess import run_shell
        rc, out, _ = await run_shell(f"playerctl {args}", timeout=5.0)
        return out.strip() if rc == 0 else ""
