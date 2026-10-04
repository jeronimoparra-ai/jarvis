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
YTMUSIC_HOME = "https://music.youtube.com"
YTMUSIC_RE = re.compile(r"music\.youtube\.com")
YTMUSIC_WORDS = ("youtube music", "ytmusic", "yt music", "youtubemusic")


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
    for words in (YTMUSIC_WORDS + ("youtube", "spotify")):
        cleaned = re.sub(r"\s+(en|de)\s+" + re.escape(words) + r"\s*$", "",
                         cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(la\s+|el\s+)?(canci[oó]n|tema|video|vídeo)\s+",
                     "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,.")


def detect_provider(text: str, default: str = "youtube") -> str:
    """'pon X en youtube music' -> 'ytmusic'; si no, el default de config."""
    low = text.lower()
    if YTMUSIC_RE.search(low) or any(w in low for w in YTMUSIC_WORDS):
        return "ytmusic"
    return default


async def search_ytmusic(query: str, timeout: float = 15.0):
    """
    Busca canción en YouTube Music sin API key.
    Devuelve (videoId, título) o (None, None).
    """
    def _search():
        try:
            from ytmusicapi import YTMusic
        except ImportError:
            return None, None
        try:
            yt = YTMusic()
            results = yt.search(query, filter="songs", limit=3)
            for item in results or []:
                vid = item.get("videoId")
                if vid:
                    artists = item.get("artists") or [{}]
                    title = f"{item.get('title', '')} - {artists[0].get('name', '')}".strip(" -")
                    return vid, title or query
        except Exception as e:
            logger.debug("YTMusic search falló: %s", e)
        return None, None
    try:
        return await asyncio.wait_for(asyncio.to_thread(_search), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        return None, None


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
        "youtube music", "ytmusic", "yt music", "en music",
        "para la música", "para la musica", "para eso", "stop", "detén",
        "sigue", "continúa", "reanuda",
    ]

    intent = "media"

    # Inyectado en main.py (y gui_server.py)
    config = None

    # Reproductor directo actual (mpv/ffplay). Se mata al poner otra cosa.
    _player = None
    _player_paused = False

    def _wait(self) -> float:
        return youtube_load_wait(self.config)

    def _default_provider(self) -> str:
        try:
            default = (self.config.get("media", {}) or {}).get(
                "default_provider", "youtube") if self.config else "youtube"
        except Exception:
            default = "youtube"
        return "ytmusic" if str(default).lower() in ("ytmusic", "music") else "youtube"

    async def _play_ytmusic(self, query: str) -> Dict[str, Any]:
        """Reproduce directo (mpv/ffplay); fallback al watch del navegador."""
        vid, title = await search_ytmusic(query)
        if not vid:
            # Sin ytmusicapi/red: cae a búsqueda YouTube normal
            logger.info("YTMusic sin resultado, fallback a YouTube.")
            return await self._play_youtube(query)
        direct = await self._direct_play(vid)
        if direct:
            return {"response": f"Reproduciendo {title}.",
                    "silent": False,
                    "audit_action": f"media:ytmusic {query[:60]}"}
        url = f"{YTMUSIC_HOME}/watch?v={vid}"
        if not await PlatformOps.open_url(url):
            return {"response": "No pude reproducir ni abrir.", "silent": False}
        return {"response": f"Abrí {title} en YouTube Music (dale play).",
                "silent": False,
                "audit_action": f"media:ytmusic {query[:60]}"}

    @classmethod
    async def _audio_url(cls, video_id: str) -> Optional[str]:
        """URL directa de audio vía yt-dlp (bestaudio)."""
        import shutil
        import sys
        if shutil.which("yt-dlp"):
            cmd = ["yt-dlp", "-f", "bestaudio", "--get-url",
                   f"https://music.youtube.com/watch?v={video_id}"]
        else:
            try:
                import yt_dlp  # noqa: F401
            except ImportError:
                return None
            cmd = [sys.executable or "python3", "-m", "yt_dlp",
                   "-f", "bestaudio", "--get-url",
                   f"https://music.youtube.com/watch?v={video_id}"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=45.0)
            url = out.decode(errors="replace").strip().splitlines()
            return url[0] if url and url[0].startswith("http") else None
        except Exception as e:
            logger.debug("yt-dlp falló: %s", e)
            return None

    @classmethod
    async def stop_player(cls) -> bool:
        """Detiene la reproducción directa si hay. True si paró algo."""
        proc = cls._player
        cls._player = None
        cls._player_paused = False
        if proc is None:
            return False
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return True

    @classmethod
    async def _direct_play(cls, video_id: str) -> bool:
        """Suena ya: mpv (preferido) o ffplay con el stream de audio."""
        stream = await cls._audio_url(video_id)
        if not stream:
            return False
        await cls.stop_player()
        import shutil
        cmd = (["mpv", "--no-video", "--no-terminal", stream]
               if shutil.which("mpv") else
               ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", stream])
        try:
            cls._player = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await asyncio.sleep(0.5)
            if cls._player.returncode not in (None, 0):
                cls._player = None
                return False
            return True
        except Exception as e:
            logger.debug("Reproductor directo falló: %s", e)
            cls._player = None
            return False

    @classmethod
    async def pause_player(cls) -> Optional[bool]:
        """Pausa (SIGSTOP) el reproductor directo. None si no hay."""
        import signal
        proc = cls._player
        if proc is None or proc.returncode is not None:
            return None
        try:
            proc.send_signal(signal.SIGSTOP)
            cls._player_paused = True
            return True
        except Exception:
            return False

    @classmethod
    async def resume_player(cls) -> Optional[bool]:
        """Reanuda (SIGCONT). None si no hay."""
        import signal
        proc = cls._player
        if proc is None or proc.returncode is not None:
            return None
        try:
            proc.send_signal(signal.SIGCONT)
            cls._player_paused = False
            return True
        except Exception:
            return False

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from core.nlu import canonicalize
        low = canonicalize(text)
        # "abre youtube" sin verbo de reproducción -> solo abrir el sitio
        if "youtube" in low and not wants_youtube_play(low):
            ok = await PlatformOps.open_url(YOUTUBE_HOME)
            if ok:
                return {"response": "", "silent": True}
            return {"response": "No pude abrir YouTube.", "silent": False}
        # "pon X" / URL / "reproduce X en youtube [music]" -> reproducir
        if wants_youtube_play(low):
            query = extract_play_query(low)
            if not query:
                ok = await PlatformOps.open_url(YOUTUBE_HOME)
                return {"response": "", "silent": True} if ok else \
                    {"response": "¿Qué pongo?", "silent": False}
            provider = detect_provider(low, self._default_provider())
            if provider == "ytmusic":
                return await self._play_ytmusic(query)
            return await self._play_youtube(query)
        # Parar del todo el reproductor directo ("para la música", "stop")
        if any(w in low for w in ("para la música", "para la musica",
                                  "para todo", "detén", "deten")) or low in (
                "para", "stop", "para eso"):
            if await self.stop_player():
                return {"response": "", "silent": True}
            if shutil.which("playerctl"):
                await self._run("stop")
                return {"response": "", "silent": True}
            return {"response": "No hay nada sonando.", "silent": False}
        # Resto: playerctl local (o reproductor directo en pausa/play)
        if "pausa" in low:
            paused = await self.pause_player()
            if paused:
                return {"response": "", "silent": True}
            if paused is None and shutil.which("playerctl") is None:
                return {"response": "Instala playerctl para control multimedia.",
                        "silent": False}
            if paused is None:
                await self._run("pause")
                return {"response": "", "silent": True}
            return {"response": "Ya está en pausa.", "silent": False}
        # Reanudar lo pausado ("sigue", "continúa")
        if any(w in low for w in ("sigue", "continua", "reanuda")):
            if await self.resume_player():
                return {"response": "", "silent": True}
        if shutil.which("playerctl") is None and self._player is None:
            return {"response": "Instala playerctl para control multimedia.",
                    "silent": False}
        if "siguiente" in low:
            await self._run("next")
            return {"response": "", "silent": True}
        if "anterior" in low:
            await self._run("previous")
            return {"response": "", "silent": True}
        if "sonando" in low or "suena" in low:
            if self._player is not None:
                return {"response": "Suena la reproducción directa de Jarvis.",
                        "silent": False}
            info = await self._run("metadata --format '{{artist}} - {{title}}'")
            info = info.strip() or "Nada en reproducción."
            return {"response": info[:200], "silent": False}
        if self._player_paused:
            await self.resume_player()
            return {"response": "", "silent": True}
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
