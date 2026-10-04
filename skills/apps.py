#!/usr/bin/env python3
"""
Application control skill for Jarvis

Handles:
- Opening applications
- Closing applications
- Switching between windows

Commands recognized:
- "abre firefox" / "abre el navegador"
- "cierra firefox"
- "abre la terminal"
- "abre visual studio code"

Foco de ventana best-effort vía wmctrl / i3-msg / swaymsg si están instalados.
"""

import asyncio
import logging
import re
import shutil
import subprocess
from typing import Dict, Any, Optional

from skills.base import Skill

logger = logging.getLogger(__name__)

class AppsSkill(Skill):
    """Control de aplicaciones (abrir/cerrar)"""
    
    patterns = [
        "abre", "abrir", "abre el", "abre la",
        "cierra", "cerrar", "cierra el", "cierra la",
        "http", "www.", ".com", ".org", ".io",
    ]
    
    intent = "apps"
    
    def __init__(self):
        super().__init__()
        self.silent = True
        
        # Application aliases
        self.app_aliases = {
            "navegador": ["firefox", "google-chrome", "chromium-browser"],
            "firefox": ["firefox"],
            "chrome": ["google-chrome", "google-chrome-stable"],
            "chromium": ["chromium-browser", "chromium"],
            "terminal": ["gnome-terminal", "konsole", "alacritty", "kitty", "xterm"],
            "editor de código": ["code", "vscode"],
            "vscode": ["code"],
            "visual studio code": ["code"],
            "spotify": ["spotify"],
            "discord": ["discord"],
            "youtube": ["firefox", "--new-window", "https://youtube.com"],
        }
        
    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute app control command
        
        Args:
            text: User command text
            intent: Intent classification (optional)
            
        Returns:
            Dict with response
        """
        text_lower = text.lower().strip()

        # URLs directas ("abre youtube.com", "abre https://...") -> navegador
        url = self._extract_url(text)
        if url and ("abre" in text_lower or "abrir" in text_lower):
            import webbrowser
            try:
                webbrowser.open(url)
                return {"response": "", "silent": True}
            except Exception as e:
                logger.error("No se pudo abrir %s: %s", url, e)
                return {"response": "No pude abrir esa dirección.", "silent": False}

        # Rutas existentes ("abre ~/Documentos", "abre /tmp/foto.png") -> xdg-open
        path = self._extract_path(text)
        if path and ("abre" in text_lower or "abrir" in text_lower):
            return await self._open_path(path)

        # Extract app name
        app_name = self._extract_app_name(text_lower)
        if not app_name:
            return {"response": "No reconozco la aplicación.", "silent": False}
            
        # Determine action
        if "abre" in text_lower or "abrir" in text_lower:
            result = await self._open_app(app_name)
            return result
            
        elif "cierra" in text_lower or "cerrar" in text_lower:
            result = await self._close_app(app_name)
            return result
            
        return {"response": "No entiendo. Dime abrir o cerrar.", "silent": False}
        
    def _extract_app_name(self, text: str) -> Optional[str]:
        """
        Extract application name from text
        
        Args:
            text: Lowercase user text
            
        Returns:
            App name or None
        """
        # Match patterns like "abre firefox", "abre el navegador"
        patterns = [
            r'abre\s+(?:el\s+|la\s+|los\s+|las\s+)?(.+)',
            r'abrir\s+(?:el\s+|la\s+|los\s+|las\s+)?(.+)',
            r'cierra\s+(?:el\s+|la\s+|los\s+|las\s+)?(.+)',
            r'cerrar\s+(?:el\s+|la\s+|los\s+|las\s+)?(.+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                app = match.group(1).strip()
                # Clean up common suffixes
                app = re.sub(r'por favor$', '', app).strip()
                return app
                
        return None
        
    @staticmethod
    def _extract_url(text: str) -> Optional[str]:
        """Detecta URLs (con o sin esquema)."""
        m = re.search(r"https?://[^\s,;]+", text)
        if m:
            return m.group(0).rstrip(".,)")
        m = re.search(r"\b(?:www\.)?[a-z0-9-]+\.(?:com|org|net|io|dev|es|edu|gov)(?:/[^\s,;]*)?", text, re.IGNORECASE)
        if m:
            url = m.group(0).rstrip(".,)")
            return url if url.startswith("http") else f"https://{url}"
        return None

    @staticmethod
    def _extract_path(text: str) -> Optional[str]:
        """Detecta rutas existentes (~/..., /..., . Archivos/carpetas)."""
        from pathlib import Path
        for token in re.findall(r"(~\/[^\s,;]*|\/[^\s,;]*|\.[^\s,;]*\/[^\s,;]*)", text):
            candidate = Path(token.rstrip(".,)")).expanduser()
            if candidate.exists():
                return str(candidate)
        return None

    async def _open_path(self, path: str) -> Dict[str, Any]:
        """Abre archivo/carpeta con la app predeterminada (xdg-open)."""
        from utils.safe_subprocess import run_exec
        rc, _, err = await run_exec(["xdg-open", path], timeout=10.0)
        if rc == 0:
            return {"response": "", "silent": True}
        logger.error("xdg-open falló para %s: %s", path, err[:200])
        return {"response": "No pude abrir esa ruta.", "silent": False}

    def _get_app_command(self, app_name: str) -> Optional[list]:
        """
        Get command to execute for an app
        
        Args:
            app_name: App name from user
            
        Returns:
            Command list or None
        """
        app_lower = app_name.lower()
        
        # Check aliases
        if app_lower in self.app_aliases:
            return self.app_aliases[app_lower]
            
        # Check if app exists in PATH
        for alias, commands in self.app_aliases.items():
            if app_lower in alias:
                return commands
                
        # Try direct command
        return [app_lower]
        
    async def _open_app(self, app_name: str) -> Dict[str, Any]:
        """
        Open an application
        
        Args:
            app_name: Name of app to open
            
        Returns:
            Dict with response
        """
        command = self._get_app_command(app_name)
        if not command:
            return {"response": f"No tengo configurada {app_name}.", "silent": False}
            
        try:
            from core.platform import PlatformOps
            ok = await PlatformOps.open_app(" ".join(command))
            if ok:
                await asyncio.sleep(0.5)  # Dar tiempo a que aparezca la ventana
                await self._focus_window(app_name)
                return {"response": "", "silent": True}
            return {"response": f"No pude abrir {app_name}.", "silent": False}
            
        except FileNotFoundError:
            return {"response": f"No encontré {app_name}.", "silent": False}
        except Exception as e:
            logger.error(f"Failed to open {app_name}: {e}")
            return {"response": f"Error al abrir {app_name}.", "silent": False}
            
    async def _focus_window(self, app_name: str) -> None:
        """Trae la ventana al frente si hay gestor compatible. Nunca falla."""
        title = app_name.strip()
        if not title:
            return
        from utils.safe_subprocess import run_exec
        try:
            if shutil.which("wmctrl"):
                rc, _, _ = await run_exec(["wmctrl", "-a", title], timeout=5.0)
                if rc == 0:
                    return
                return
            if shutil.which("i3-msg"):
                await run_exec(["i3-msg", f'[title="{title}"] focus'], timeout=5.0)
                return
            if shutil.which("swaymsg"):
                await run_exec(["swaymsg", f'[title="{title}"] focus'], timeout=5.0)
                return
        except Exception as e:
            logger.debug("Foco de ventana no disponible: %s", e)

    async def _close_app(self, app_name: str) -> Dict[str, Any]:
        """
        Close an application
        
        Args:
            app_name: Name of app to close
            
        Returns:
            Dict with response
        """
        command = self._get_app_command(app_name)
        if not command:
            return {"response": f"No tengo configurada {app_name}.", "silent": False}
            
        # Use the first command name for killing
        process_name = command[0]

        from utils.safe_subprocess import run_exec
        try:
            from core.platform import IS_WINDOWS
            if IS_WINDOWS:
                await run_exec(["taskkill", "/IM", process_name, "/F"],
                               timeout=10.0)
                return {"response": "", "silent": True}
            # Try graceful close first
            await run_exec(["pkill", "-15", process_name], timeout=5.0)

            await asyncio.sleep(0.5)

            # Force kill if still running
            await run_exec(["pkill", "-9", process_name], timeout=5.0)

            return {"response": "", "silent": True}

        except Exception as e:
            logger.error(f"Failed to close {app_name}: {e}")
            return {"response": f"Error al cerrar {app_name}.", "silent": False}
