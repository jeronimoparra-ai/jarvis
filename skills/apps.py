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
        "cierra", "cerrar", "cierra el", "cierra la"
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
            await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await asyncio.sleep(0.5)  # Dar tiempo a que aparezca la ventana
            await self._focus_window(app_name)

            return {"response": "", "silent": True}
            
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
        try:
            if shutil.which("wmctrl"):
                proc = await asyncio.create_subprocess_exec(
                    "wmctrl", "-a", title,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL)
                await proc.wait()
                return
            if shutil.which("i3-msg"):
                proc = await asyncio.create_subprocess_exec(
                    "i3-msg", f'[title="{title}"] focus',
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL)
                await proc.wait()
                return
            if shutil.which("swaymsg"):
                proc = await asyncio.create_subprocess_exec(
                    "swaymsg", f'[title="{title}"] focus',
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL)
                await proc.wait()
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
        
        try:
            # Try graceful close first
            await asyncio.create_subprocess_exec(
                "pkill", "-15", process_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            
            await asyncio.sleep(0.5)
            
            # Force kill if still running
            await asyncio.create_subprocess_exec(
                "pkill", "-9", process_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            
            return {"response": "", "silent": True}
            
        except Exception as e:
            logger.error(f"Failed to close {app_name}: {e}")
            return {"response": f"Error al cerrar {app_name}.", "silent": False}
