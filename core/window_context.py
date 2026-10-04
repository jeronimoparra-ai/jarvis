#!/usr/bin/env python3
"""
Contexto de la ventana activa (best-effort, sin dependencias nuevas).

Orden de intentos: swaymsg (Sway) → hyprctl (Hyprland) → xdotool/xprop (X11).
En Wayland/GNOME sin esas herramientas: no disponible (se informa).
"""

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WindowInfo:
    title: str = ""
    wm_class: str = ""
    backend: str = ""


async def _run(cmd: str, timeout: float = 3.0) -> tuple[int, str]:
    from utils.safe_subprocess import run_shell
    rc, out, _ = await run_shell(cmd, timeout=timeout)
    return rc, out.strip()


async def get_active_window() -> Optional[WindowInfo]:
    """Ventana enfocada o None si no se puede detectar."""
    # Sway
    if shutil.which("swaymsg"):
        rc, out = await _run("swaymsg -t get_tree")
        if rc == 0:
            try:
                node = _find_focused(json.loads(out))
                if node:
                    return WindowInfo(
                        title=str(node.get("name", "")),
                        wm_class=str((node.get("window_properties") or {}).get("class", "")),
                        backend="sway")
            except (json.JSONDecodeError, AttributeError):
                pass
    # Hyprland
    if shutil.which("hyprctl"):
        rc, out = await _run("hyprctl activewindow -j")
        if rc == 0:
            try:
                data = json.loads(out)
                return WindowInfo(title=str(data.get("title", "")),
                                  wm_class=str(data.get("class", "")),
                                  backend="hyprland")
            except json.JSONDecodeError:
                pass
    # X11
    if shutil.which("xdotool"):
        rc, out = await _run("xdotool getactivewindow getwindowname")
        if rc == 0 and out:
            wm_class = ""
            if shutil.which("xprop"):
                rc2, out2 = await _run("xprop -id $(xdotool getactivewindow) WM_CLASS")
                if rc2 == 0 and out2:
                    wm_class = out2.split("=")[-1].strip().strip('"')
            return WindowInfo(title=out, wm_class=wm_class, backend="x11")
    return None


def _find_focused(node: dict) -> Optional[dict]:
    if node.get("focused"):
        return node
    for child in list(node.get("nodes", [])) + list(node.get("floating_nodes", [])):
        found = _find_focused(child)
        if found:
            return found
    return None


async def close_active_window() -> bool:
    """Cierra la ventana enfocada. True si se envió el cierre."""
    if shutil.which("swaymsg"):
        rc, _ = await _run("swaymsg kill")
        if rc == 0:
            return True
    if shutil.which("hyprctl"):
        rc, _ = await _run("hyprctl dispatch killactive")
        if rc == 0:
            return True
    if shutil.which("xdotool"):
        rc, _ = await _run("xdotool getactivewindow windowkill")
        if rc == 0:
            return True
    return False


async def focus_window_by_class(wm_class: str) -> bool:
    """Enfoca por clase (X11/wmctrl) o título (sway/i3)."""
    if not wm_class:
        return False
    if shutil.which("wmctrl"):
        rc, _ = await _run(f"wmctrl -a '{wm_class}'")
        if rc == 0:
            return True
    for tool, tmpl in (("swaymsg", "[class=\"{c}\"] focus"),
                       ("i3-msg", "[class=\"{c}\"] focus")):
        if shutil.which(tool):
            rc, _ = await _run(f"{tool} '{tmpl.format(c=wm_class)}'")
            if rc == 0:
                return True
    return False
