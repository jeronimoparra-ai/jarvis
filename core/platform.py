#!/usr/bin/env python3
"""
Capa cross-platform: una sola API, dos backends.

- Linux: xdg-open, pactl/wpctl, loginctl, gnome-screenshot/scrot,
  notify-send, wl-copy/xclip/xsel, wmctrl/xdotool/swaymsg/hyprctl.
- Windows: os.startfile, PowerShell (volumen/clipboard), rundll32 (lock),
  taskkill/AppActivate best-effort, snipping best-effort.

Detecta con platform.system(). Import seguro en ambos SO (sin deps nuevas).
"""

import asyncio
import logging
import os
import platform as _platform
import shutil
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SYSTEM = _platform.system()  # "Linux" | "Windows" | ...
IS_WINDOWS = SYSTEM == "Windows"
IS_LINUX = SYSTEM == "Linux"


async def _sh(cmd: str, timeout: float = 8.0) -> tuple[int, str]:
    """Ejecuta shell, devuelve (rc, stdout). Nunca lanza excepción."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode(errors="replace").strip()
    except Exception as e:
        logger.debug("platform _sh falló '%s': %s", cmd, e)
        return 1, ""


def _sh_sync(cmd: str, timeout: float = 8.0) -> tuple[int, str]:
    import subprocess
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True,
                             timeout=timeout)
        return out.returncode, out.stdout.decode(errors="replace").strip()
    except Exception as e:
        logger.debug("platform _sh_sync falló '%s': %s", cmd, e)
        return 1, ""


# ---------------------------------------------------------------- volume

async def _linux_volume_get() -> Optional[int]:
    if shutil.which("pactl"):
        rc, out = await _sh("pactl get-sink-volume @DEFAULT_SINK@")
        if rc == 0:
            import re
            m = re.search(r"(\d+)%", out)
            if m:
                return int(m.group(1))
    if shutil.which("wpctl"):
        rc, out = await _sh("wpctl get-volume @DEFAULT_AUDIO_SINK@")
        if rc == 0:
            import re
            m = re.search(r"Volume:\s*([\d.]+)", out)
            if m:
                return int(float(m.group(1)) * 100)
    return None


async def _linux_volume_set(percent: Optional[int] = None,
                            delta: Optional[int] = None) -> bool:
    """percent absoluto (0-100) o delta (+/-). True si funcionó."""
    backend = "pactl" if shutil.which("pactl") else (
        "wpctl" if shutil.which("wpctl") else None)
    if backend is None:
        return False
    if percent is not None:
        percent = max(0, min(150, percent))
        cmd = (f"pactl set-sink-volume @DEFAULT_SINK@ {percent}%"
               if backend == "pactl" else
               f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {percent}%")
    elif delta is not None:
        sign = "+" if delta >= 0 else "-"
        cmd = (f"pactl set-sink-volume @DEFAULT_SINK@ {sign}{abs(delta)}%"
               if backend == "pactl" else
               f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {abs(delta)}%{sign}")
    else:
        return False
    rc, _ = await _sh(cmd)
    return rc == 0


async def _windows_volume_set(percent: Optional[int] = None,
                              delta: Optional[int] = None) -> bool:
    """nircmd si existe; si no, teclas multimedia reales (keybd_event)."""
    if shutil.which("nircmd"):
        if percent is not None:
            val = int(max(0, min(100, percent)) / 100 * 65535)
            rc, _ = await _sh(f"nircmd setsysvolume {val}")
            return rc == 0
        if delta is not None:
            rc, _ = await _sh(f"nircmd changesysvolume {int(delta) * 655}")
            return rc == 0
        return False
    # keybd_event con VK_VOLUME_UP (0xAF) / DOWN (0xAE): ~2% por toque
    if delta is None and percent is None:
        return False
    steps = 1 if percent is not None else max(1, min(25, abs(int(delta)) // 2))
    vk = "0xAF" if (delta or 1) > 0 else "0xAE"
    ps = ("Add-Type -MemberDefinition '[DllImport(\"user32.dll\")] "
          "public static extern void keybd_event(byte b,int u,int x,int y);' "
          f"-Name V -Namespace W; 1..{steps} | %{{"
          f"[W.V]::keybd_event({vk},0,1,0); "
          f"[W.V]::keybd_event({vk},0,3,0); Start-Sleep -Milliseconds 40}}")
    rc, _ = await _sh(f'powershell -NoProfile -Command "{ps}"', timeout=30.0)
    return rc == 0


class PlatformOps:
    """Operaciones de SO con la misma firma en Linux y Windows."""

    # -- abrir -----------------------------------------------------------
    @staticmethod
    async def open_url(url: str) -> bool:
        try:
            if IS_WINDOWS:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None, lambda: bool(webbrowser.open(url)))
            ok = await asyncio.to_thread(webbrowser.open, url)
            return bool(ok)
        except Exception as e:
            logger.debug("open_url falló: %s", e)
            return False

    @staticmethod
    async def open_app(name_or_path: str) -> bool:
        """Lanza app/comando/ruta. True si se pudo spawnear."""
        target = name_or_path.strip()
        if IS_WINDOWS:
            try:
                if os.path.exists(target):
                    os.startfile(target)  # noqa: S606 - ruta validada por existir
                    return True
                rc, _ = await _sh(f'cmd /c start "" "{target}"')
                return rc == 0
            except Exception as e:
                logger.debug("open_app win falló: %s", e)
                return False
        # Linux: ruta existente -> xdg-open; resto -> exec directo
        if os.path.exists(os.path.expanduser(target)):
            rc, _ = await _sh(f"xdg-open '{os.path.expanduser(target)}'")
            return rc == 0
        try:
            import shlex
            parts = shlex.split(target)
            proc = await asyncio.create_subprocess_exec(
                *parts, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await asyncio.sleep(0.3)
            return proc.returncode is None or proc.returncode == 0
        except Exception as e:
            logger.debug("open_app linux falló: %s", e)
            return False

    # -- volumen ---------------------------------------------------------
    @staticmethod
    async def set_volume(percent: Optional[int] = None,
                         delta: Optional[int] = None) -> bool:
        if IS_WINDOWS:
            return await _windows_volume_set(percent, delta)
        return await _linux_volume_set(percent, delta)

    @staticmethod
    async def get_volume() -> Optional[int]:
        if IS_WINDOWS:
            return None  # best-effort: sin lectura fiable sin nircmd
        return await _linux_volume_get()

    # -- sesión / sistema -------------------------------------------------
    @staticmethod
    async def lock_session() -> bool:
        if IS_WINDOWS:
            rc, _ = await _sh("rundll32.exe user32.dll,LockWorkStation")
            return rc == 0
        rc, _ = await _sh("loginctl lock-session")
        return rc == 0

    @staticmethod
    async def screenshot(path: str) -> bool:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if IS_WINDOWS:
            ps = (f"Add-Type -AssemblyName System.Windows.Forms;"
                  f"$b=New-Object Drawing.Bitmap([Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,"
                  f"[Windows.Forms.Screen]::PrimaryScreen.Bounds.Height);"
                  f"$g=[Drawing.Graphics]::FromImage($b);"
                  f"$g.CopyFromScreen(0,0,0,0,$b.Size);"
                  f"$b.Save('{path}')")
            rc, _ = await _sh(f'powershell -NoProfile -Command "{ps}"', timeout=15.0)
            return rc == 0 and Path(path).exists()
        for cmd in (f"gnome-screenshot -f '{path}'",
                    f"scrot '{path}'",
                    f"import -window root '{path}'"):
            tool = cmd.split()[0]
            if shutil.which(tool):
                rc, _ = await _sh(cmd)
                if rc == 0 and Path(path).exists():
                    return True
        return False

    @staticmethod
    async def notify(title: str, message: str) -> bool:
        if IS_WINDOWS:
            ps = (f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                  f"ContentType=WindowsRuntime] > $null; "
                  f"New-BurntToastNotification -Text '{title}', '{message}' 2>$null")
            rc, _ = await _sh(f'powershell -NoProfile -Command "{ps}"')
            if rc == 0:
                return True
            # Fallback msg popup no bloqueante
            await _sh(f'msg * "{title}: {message}"')
            return True
        if shutil.which("notify-send"):
            rc, _ = await _sh(f"notify-send '{title}' '{message}'")
            return rc == 0
        return False

    # -- portapapeles ------------------------------------------------------
    @staticmethod
    async def copy_to_clipboard(text: str) -> bool:
        if IS_WINDOWS:
            # clip.exe con UTF-16LE (fiable); Set-Clipboard como respaldo
            try:
                import subprocess
                p = subprocess.run(["clip"], input=text.encode("utf-16le"),
                                   capture_output=True, timeout=8)
                if p.returncode == 0:
                    return True
            except Exception as e:
                logger.debug("clip falló: %s", e)
            safe = text.replace("'", "''")[:2000]
            rc, _ = await _sh(
                "powershell -NoProfile -Command "
                f"\"Set-Clipboard -Value '{safe}'\"")
            return rc == 0
        cmds = []
        if shutil.which("wl-copy"):
            cmds.append(["wl-copy"])
        if shutil.which("xclip"):
            cmds.append(["xclip", "-selection", "clipboard"])
        if shutil.which("xsel"):
            cmds.append(["xsel", "--clipboard", "--input"])
        for cmd in cmds:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL)
                await asyncio.wait_for(
                    proc.communicate(text.encode("utf-8")), timeout=5.0)
                if proc.returncode == 0:
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    async def paste_hotkey() -> bool:
        """Ctrl+V en la ventana enfocada (best-effort)."""
        if IS_WINDOWS:
            ps = ("$w=New-Object -ComObject WScript.Shell;"
                  "$w.SendKeys('^v')")
            rc, _ = await _sh(f'powershell -NoProfile -Command "{ps}"')
            return rc == 0
        if shutil.which("xdotool"):
            await asyncio.sleep(0.3)
            rc, _ = await _sh("xdotool key ctrl+v")
            return rc == 0
        if shutil.which("wtype"):
            rc, _ = await _sh("wtype -M ctrl v")
            return rc == 0
        return False

    # -- ventanas ----------------------------------------------------------
    @staticmethod
    async def focus_app_window(name: str) -> bool:
        """Trae al frente una ventana por clase/título (best-effort)."""
        if not name:
            return False
        if IS_WINDOWS:
            ps = (f"$w=New-Object -ComObject WScript.Shell;"
                  f"$w.AppActivate('{name}')")
            rc, _ = await _sh(f'powershell -NoProfile -Command "{ps}"')
            return rc == 0
        from core.window_context import focus_window_by_class
        return await focus_window_by_class(name)

    @staticmethod
    async def close_active_window() -> bool:
        if IS_WINDOWS:
            ps = ("$w=New-Object -ComObject WScript.Shell;"
                  "$w.SendKeys('%{F4}')")
            rc, _ = await _sh(f'powershell -NoProfile -Command "{ps}"')
            return rc == 0
        from core.window_context import close_active_window
        return await close_active_window()

    @staticmethod
    async def get_active_window_title() -> str:
        if IS_WINDOWS:
            ps = ("Add-Type @'\n"
                  "using System;\n"
                  "using System.Runtime.InteropServices;\n"
                  "public class W { [DllImport(\"user32.dll\")] "
                  "public static extern IntPtr GetForegroundWindow(); }\n"
                  "'@; [W]::GetForegroundWindow()")
            rc, out = await _sh(f'powershell -NoProfile -Command "{ps}"')
            return out if rc == 0 else ""
        from core.window_context import get_active_window
        info = await get_active_window()
        return (info.title or info.wm_class) if info else ""

    # -- estado ------------------------------------------------------------
    @staticmethod
    async def system_status() -> Dict[str, Any]:
        """cpu_load, cpu_count, ram_pct, disk (home), battery — lo disponible."""
        import os as _os
        data: Dict[str, Any] = {"os": SYSTEM}
        if IS_WINDOWS:
            rc, out = await _sh(
                'powershell -NoProfile -Command '
                '"(Get-CimInstance Win32_Processor).LoadPercentage"')
            try:
                data["cpu_pct"] = int(out)
            except ValueError:
                pass
            rc, out = await _sh(
                'powershell -NoProfile -Command '
                '"[math]::Round((Get-CimInstance Win32_OperatingSystem | '
                'Select-Object @{n=\"p\";e={$_.TotalVisibleMemorySize-$_.FreePhysicalMemory}}).p / '
                '(Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize*100)"')
            try:
                data["ram_pct"] = int(out)
            except ValueError:
                pass
            return data
        try:
            load1, _, _ = _os.getloadavg()
            data["cpu_load"] = round(load1, 2)
            data["cpu_count"] = _os.cpu_count() or 1
        except OSError:
            pass
        rc, out = await _sh("free | awk '/Mem:/ {printf \"%d\", $3/$2*100}'")
        if rc == 0 and out.isdigit():
            data["ram_pct"] = int(out)
        try:
            st = os.statvfs(str(Path.home()))
            data["disk_free_gb"] = round(st.f_bavail * st.f_frsize / 1e9)
            data["disk_used_pct"] = round(100 * (1 - st.f_bavail / st.f_blocks))
        except OSError:
            pass
        base = Path("/sys/class/power_supply")
        try:
            for bat in sorted(base.glob("BAT*")):
                data["battery_pct"] = (bat / "capacity").read_text().strip()
                data["battery_status"] = (bat / "status").read_text().strip()
                break
        except OSError:
            pass
        return data
