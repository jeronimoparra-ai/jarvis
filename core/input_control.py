#!/usr/bin/env python3
"""
Automatización de cursor y teclado (UI automation).

- Linux X11: xdotool completo (mover/click/teclear).
- Linux Wayland: lectura (posición, ventanas XWayland) + portapapeles;
  mover/clicar/teclear NO lo permite el compositor (GNOME). wtype solo
  en compositores con protocolo virtual-keyboard (Sway/Hyprland).
- Windows: PowerShell SendKeys / mouse_event best-effort.
- Sin backend: error claro, nunca crash.

Seguridad (config input_control):
  enabled, allow_typing, max_type_chars.
  type_text rechaza comandos shell peligrosos.
"""

import asyncio
import logging
import re
import shutil
from typing import Optional

from core.platform import IS_WINDOWS

logger = logging.getLogger(__name__)

# Fragmentos que nunca se escriben vía type_text (inyección de shell)
_BLOCKED_TYPING = (
    "rm -rf", "rm -fr", ":(){", "mkfs", "dd if=", "dd of=",
    "shutdown", "poweroff", "reboot", "halt", "> /dev/",
    "chmod 777 /", "chown -R /",
)


def _cfg(config, key: str, default):
    try:
        return config.get(key, default) if config else default
    except Exception:
        return default


class InputControl:
    """Cursor + teclado con backend según SO y guardas de config."""

    def __init__(self, config=None):
        self.config = config
        self.enabled = bool(_cfg(config, "input_control.enabled", True))
        self.allow_typing = bool(_cfg(config, "input_control.allow_typing", True))
        self.max_type_chars = int(_cfg(config, "input_control.max_type_chars", 500))

    # -- backend ---------------------------------------------------------
    @staticmethod
    def backend() -> Optional[str]:
        if IS_WINDOWS:
            return "powershell"
        if shutil.which("xdotool"):
            return "xdotool"
        if shutil.which("ydotool"):
            return "ydotool"
        return None

    def _guard(self, needs_typing: bool = False) -> Optional[str]:
        import os
        if not self.enabled:
            return "Automatización de cursor desactivada en config."
        if needs_typing and not self.allow_typing:
            return "Escribir texto está desactivado en config."
        if self.backend() is None:
            return ("Sin backend de automatización "
                    "(instala xdotool en Linux).")
        if os.getenv("WAYLAND_DISPLAY") and not os.getenv("DISPLAY"):
            return ("Wayland puro: el compositor no permite mover/clicar "
                    "por CLI (solo lectura y portapapeles).")
        return None

    @staticmethod
    def _typing_safe(text: str) -> bool:
        low = text.lower()
        return not any(b in low for b in _BLOCKED_TYPING)

    # -- Linux xdotool/ydotool -------------------------------------------
    async def _lin(self, args: str, timeout: float = 8.0) -> bool:
        tool = "xdotool" if shutil.which("xdotool") else "ydotool"
        try:
            proc = await asyncio.create_subprocess_shell(
                f"{tool} {args}", stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), timeout=timeout)
            return proc.returncode == 0
        except Exception as e:
            logger.debug("input %s falló: %s", args, e)
            return False

    # -- Windows PowerShell ----------------------------------------------
    async def _win_keys(self, sendkeys: str) -> bool:
        from core.platform import _sh
        ps = ("Add-Type -AssemblyName System.Windows.Forms; "
              f"[Windows.Forms.SendKeys]::SendWait('{sendkeys}')")
        rc, _ = await _sh(f'powershell -NoProfile -Command "{ps}"')
        return rc == 0

    async def _win_click(self, button: str = "left") -> bool:
        from core.platform import _sh
        flag = "0x02" if button == "right" else "0x02"
        up = "0x08" if button == "right" else "0x04"
        down = "0x08" if button == "right" else "0x02"
        _ = (flag, up)
        ps = ("Add-Type -MemberDefinition '[DllImport(\"user32.dll\")] "
              "public static extern void mouse_event(int d,int u,int x,int y,int e);' "
              f"-Name M -Namespace W; [W.M]::mouse_event({down},0,0,0,0); "
              f"[W.M]::mouse_event({up},0,0,0,0)")
        rc, _ = await _sh(f'powershell -NoProfile -Command "{ps}"')
        return rc == 0

    # -- API ---------------------------------------------------------------
    async def move_to(self, x: int, y: int) -> bool:
        """Mueve el cursor a coordenadas absolutas."""
        if (err := self._guard()) is not None:
            logger.warning("move_to bloqueado: %s", err)
            return False
        if IS_WINDOWS:
            from core.platform import _sh
            ps = (f"Add-Type -AssemblyName System.Windows.Forms; "
                  f"[Windows.Forms.Cursor]::Position = "
                  f"New-Object Drawing.Point({int(x)},{int(y)})")
            rc, _ = await _sh(f'powershell -NoProfile -Command "{ps}"')
            return rc == 0
        return await self._lin(f"mousemove {int(x)} {int(y)}")

    async def click(self, button: str = "left", clicks: int = 1) -> bool:
        if (err := self._guard()) is not None:
            logger.warning("click bloqueado: %s", err)
            return False
        button = button if button in ("left", "right") else "left"
        clicks = max(1, min(3, clicks))
        if IS_WINDOWS:
            ok = True
            for _ in range(clicks):
                ok = await self._win_click(button) and ok
                await asyncio.sleep(0.15)
            return ok
        btn = "1" if button == "left" else "3"
        return await self._lin(f"click --repeat {clicks} {btn}")

    async def hotkey(self, *keys: str) -> bool:
        """Atajo: hotkey('ctrl','l'), hotkey('ctrl','shift','p')."""
        if (err := self._guard()) is not None:
            logger.warning("hotkey bloqueado: %s", err)
            return False
        if IS_WINDOWS:
            combo = "".join(f"^" if k.lower() in ("ctrl", "control") else
                            f"+" if k.lower() == "shift" else
                            f"%" if k.lower() == "alt" else
                            f"{{{k}}}" for k in keys)
            return await self._win_keys(combo)
        combo = "+".join(keys)
        return await self._lin(f"key {combo}")

    async def type_text(self, text: str, interval: float = 0.02) -> bool:
        """Escribe texto (con guardas de seguridad)."""
        if (err := self._guard(needs_typing=True)) is not None:
            logger.warning("type_text bloqueado: %s", err)
            return False
        text = text[:self.max_type_chars]
        if not text or not self._typing_safe(text):
            logger.warning("type_text rechazado por seguridad.")
            return False
        if IS_WINDOWS:
            from core.platform import _sh
            safe = text.replace("'", "''")
            ps = (f"Add-Type -AssemblyName System.Windows.Forms; "
                  f"[Windows.Forms.SendKeys]::SendWait('{safe}')")
            rc, _ = await _sh(f'powershell -NoProfile -Command "{ps}"',
                              timeout=20.0)
            return rc == 0
        # xdotool type con --delay; escapa comillas simples para shell
        safe = text.replace("'", "'\\''")
        ms = max(0, int(interval * 1000))
        return await self._lin(f"type --delay {ms} '{safe}'", timeout=30.0)

    async def press(self, key: str) -> bool:
        """Tecla especial: Return, space, escape, Tab, Up..."""
        if (err := self._guard()) is not None:
            logger.warning("press bloqueado: %s", err)
            return False
        key = {"enter": "Return", "return": "Return", "esc": "Escape",
               "space": "space"}.get(key.lower(), key)
        if IS_WINDOWS:
            return await self._win_keys(f"{{{key.upper()}}}")
        return await self._lin(f"key {key}")

    async def wait(self, seconds: float) -> bool:
        await asyncio.sleep(max(0.0, min(30.0, seconds)))
        return True

    @staticmethod
    def extract_coords(text: str) -> Optional[tuple[int, int]]:
        """'mueve el cursor a 500 300' -> (500, 300)."""
        m = re.search(r"(\d{1,4})\s*[x,]\s*(\d{1,4})", text)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None
