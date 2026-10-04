#!/usr/bin/env python3
"""
System control skill for Jarvis

Handles:
- Volume control
- Brightness control
- Shutdown/restart
- Suspend
- System info

Commands recognized:
- "sube el volumen" / "baja el volumen"
- "aumenta brillo" / "reduce brillo"
- "apaga" / "apagar"
- "reinicia" / "reiniciar"
- "suspende" / "suspender"
- "información del sistema"

Energía vía systemctl; apagar/reiniciar/suspender exigen "confirma".
"""

import asyncio
import logging
import subprocess
import re
from typing import Dict, Any, Optional

from skills.base import Skill

logger = logging.getLogger(__name__)

class SystemSkill(Skill):
    """Control de sistema (volumen, brillo, energía)"""
    
    patterns = [
        "volumen", "brillo", "apaga", "apagar", "reinicia", "reiniciar",
        "suspende", "suspender", "información del sistema", "estado del sistema",
        "captura", "pantallazo", "bloquea", "bloquear", "wifi",
    ]
    
    intent = "system"
    
    def __init__(self):
        super().__init__()
        self.silent = True  # Most system commands are silent
        
    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute system command
        
        Args:
            text: User command text
            intent: Intent classification (optional)
            
        Returns:
            Dict with response and silent flag
        """
        text_lower = text.lower().strip()
        
        # Volume control
        if "volumen" in text_lower or "volumen" in text_lower:
            result = await self._control_volume(text_lower)
            return result
            
        # Brightness control
        if "brillo" in text_lower:
            result = await self._control_brightness(text_lower)
            return result
            
        # Wifi (antes que "apaga" genérico): on/estado directo, off con confirma
        if "wifi" in text_lower or "wi-fi" in text_lower:
            return await self._control_wifi(text_lower)

        # Bloquear sesión (reversible al instante: sin confirmación)
        if "bloquea" in text_lower or "bloquear" in text_lower:
            await self._system_command("loginctl lock-session")
            return {"response": "", "silent": True}

        # Shutdown (alto riesgo: pending por voz o "confirma" en la frase)
        if "apaga" in text_lower:
            return self._ask_power(
                text_lower, "apagar el equipo", "Apagando.",
                lambda: self._system_command("systemctl poweroff"))

        # Restart (alto riesgo)
        if "reinicia" in text_lower or "reiniciar" in text_lower:
            return self._ask_power(
                text_lower, "reiniciar el equipo", "Reiniciando.",
                lambda: self._system_command("systemctl reboot"))

        # Suspend (riesgo medio: también confirma)
        if "suspende" in text_lower or "suspender" in text_lower:
            return self._ask_power(
                text_lower, "suspender el equipo", "Suspendiendo.",
                lambda: self._system_command("systemctl suspend"))
            
        # Screenshot
        if "captura" in text_lower or "pantallazo" in text_lower:
            return await self._take_screenshot()

        # System info
        if "información del sistema" in text_lower or "estado del sistema" in text_lower:
            result = await self._get_system_info()
            return {"response": result, "silent": False}
            
        # Unknown system command
        return {
            "response": "Comando de sistema no reconocido.",
            "silent": False
        }
        
    async def _control_volume(self, text: str) -> Dict[str, Any]:
        """
        Control system volume using amixer or pactl
        
        Args:
            text: User command text
            
        Returns:
            Dict with response
        """
        try:
            # Extract percentage if specified
            percent = 5  # Default step
            percent_match = re.search(r'(\d+)%', text)
            if percent_match:
                percent = int(percent_match.group(1))
            
            import shutil
            backend = "pactl" if shutil.which("pactl") else (
                "wpctl" if shutil.which("wpctl") else None)
            if backend is None:
                return {"response": "Control de volumen no disponible (falta pactl o wpctl).",
                        "silent": False}
            # Determine direction (pactl o wpctl según disponibilidad)
            if "subir" in text or "sube" in text or "aumentar" in text or "aumenta" in text:
                if "mute" in text or "silencio" in text:
                    await self._mute_cmd(backend, True)
                    return {"response": "Volumen silenciado.", "silent": False}
                await self._volume_cmd(backend, percent, up=True)
                return {"response": "", "silent": True, "reversible": True,
                        "audit_action": f"system:volumen+{percent}%",
                        "undo_payload": {"type": "volume_step",
                                         "direction": "down", "percent": percent}}

            elif "bajar" in text or "baja" in text or "reducir" in text or "reduce" in text:
                await self._volume_cmd(backend, percent, up=False)
                return {"response": "", "silent": True, "reversible": True,
                        "audit_action": f"system:volumen-{percent}%",
                        "undo_payload": {"type": "volume_step",
                                         "direction": "up", "percent": percent}}

            elif "mute" in text or "silencio" in text:
                await self._mute_cmd(backend, True)
                return {"response": "Volumen silenciado.", "silent": False}
                
            else:
                return {"response": "Especifica subir, bajar o silenciar.", "silent": False}
                
        except Exception as e:
            logger.error(f"Volume control error: {e}")
            return {"response": "Error al controlar volumen.", "silent": False}
            
    async def _control_brightness(self, text: str) -> Dict[str, Any]:
        """
        Control screen brightness using brightnessctl or xrandr
        
        Args:
            text: User command text
            
        Returns:
            Dict with response
        """
        try:
            percent = 10  # Default step
            percent_match = re.search(r'(\d+)%', text)
            if percent_match:
                percent = int(percent_match.group(1))
            
            # Try brightnessctl first
            if "subir" in text or "sube" in text or "aumentar" in text or "aumenta" in text:
                result = await self._run_command(f"brightnessctl set +{percent}%")
                if result.returncode == 0:
                    return {"response": "", "silent": True}
                    
            elif "bajar" in text or "baja" in text or "reducir" in text or "reduce" in text:
                result = await self._run_command(f"brightnessctl set {percent}%-")
                if result.returncode == 0:
                    return {"response": "", "silent": True}
                    
            return {"response": "Error al controlar brillo.", "silent": False}
                
        except Exception as e:
            logger.error(f"Brightness control error: {e}")
            return {"response": "Error al controlar brillo.", "silent": False}
            
    async def _get_system_info(self) -> str:
        """
        Get system information
        
        Returns:
            System info string
        """
        try:
            # Get uptime
            uptime_result = await self._run_command("uptime -p")
            uptime = uptime_result.stdout.strip() if uptime_result.returncode == 0 else "N/A"
            
            # Get battery
            battery_result = await self._run_command("cat /sys/class/power_supply/BAT0/capacity")
            battery = battery_result.stdout.strip() if battery_result.returncode == 0 else "N/A"
            
            # Get memory
            mem_result = await self._run_command("free -h | grep Mem")
            mem = mem_result.stdout.strip() if mem_result.returncode == 0 else "N/A"
            
            return f"Uptime: {uptime}, Batería: {battery}%, Memoria: {mem}"
            
        except Exception as e:
            logger.error(f"System info error: {e}")
            return "Error al obtener información del sistema."
            
    async def _take_screenshot(self) -> Dict[str, Any]:
        """Captura de pantalla a ~/Imágenes/jarvis-*.png."""
        import shutil
        from datetime import datetime
        from pathlib import Path
        if shutil.which("gnome-screenshot") is None:
            return {"response": "Instala gnome-screenshot para capturas.",
                    "silent": False}
        dest = Path.home() / "Imágenes"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"jarvis-{datetime.now():%Y%m%d-%H%M%S}.png"
        rc = await self._system_command(f"gnome-screenshot -f '{path}'")
        if rc == 0:
            return {"response": "", "silent": True}
        return {"response": "No se pudo tomar la captura.", "silent": False}

    def _ask_power(self, text_lower: str, description: str, done_msg: str,
                   action) -> Dict[str, Any]:
        """
        Alto riesgo: con "confirma" en la frase ejecuta ya (compat);
        si no, devuelve deferred para que el router abra un pending por voz.
        """

        async def _run():
            await action()
            return {"response": done_msg, "silent": False,
                    "audit_action": f"system:{description}"}

        return {"response": f"Vas a {description}. Di confirma o cancela.",
                "silent": False, "requires_confirmation": True,
                "deferred_execute": _run,
                "audit_action": f"system:{description}"}

    async def _volume_cmd(self, backend: str, percent: int, up: bool) -> int:
        """Sube/baja el volumen un porcentaje."""
        if backend == "pactl":
            sign = "+" if up else "-"
            return await self._system_command(
                f"pactl set-sink-volume @DEFAULT_SINK@ {sign}{percent}%")
        suffix = "+" if up else "-"
        return await self._system_command(
            f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {percent}%{suffix}")

    async def _mute_cmd(self, backend: str, toggle: bool = True) -> int:
        """Silencia/alterna el volumen."""
        if backend == "pactl":
            return await self._system_command(
                "pactl set-sink-mute @DEFAULT_SINK@ toggle" if toggle
                else "pactl set-sink-mute @DEFAULT_SINK@ 1")
        return await self._system_command(
            "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle" if toggle
            else "wpctl set-mute @DEFAULT_AUDIO_SINK@ 1")

    async def _control_wifi(self, text: str) -> Dict[str, Any]:
        """Wifi: encender/estado directos; apagar pide confirma."""
        import shutil
        if shutil.which("nmcli") is None:
            return {"response": "nmcli no disponible para gestionar el wifi.",
                    "silent": False}
        if "enciende" in text or "activa" in text or "conecta" in text:
            await self._system_command("nmcli radio wifi on")
            return {"response": "", "silent": True}
        if "apaga" in text or "desactiva" in text or "desconecta" in text:
            async def _wifi_off():
                await self._system_command("nmcli radio wifi off")
                return {"response": "", "silent": True,
                        "audit_action": "system:apagar el wifi"}
            return {"response": "Vas a apagar el wifi. Di confirma o cancela.",
                    "silent": False, "requires_confirmation": True,
                    "deferred_execute": _wifi_off,
                    "audit_action": "system:apagar el wifi"}
        result = await self._run_command("nmcli -t -f STATE general")
        state = result.stdout.strip() if result.returncode == 0 else "desconocido"
        return {"response": f"Wifi: {state}.", "silent": False}

    async def _system_command(self, command: str) -> int:
        """
        Run system command (e.g., systemctl)
        
        Args:
            command: Command to execute
            
        Returns:
            Return code
        """
        try:
            # Use subprocess for system commands (requires privileges)
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"Command failed: {stderr.decode()}")
                
            return process.returncode
            
        except Exception as e:
            logger.error(f"System command error: {e}")
            return 1
            
    async def _run_command(self, command: str):
        """Run a shell command. Devuelve SimpleNamespace(stdout, stderr, returncode)."""
        from types import SimpleNamespace
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return SimpleNamespace(
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            returncode=process.returncode,
        )


async def register_system_undo_handlers(audit) -> None:
    """Registra en el audit cómo deshacer pasos de volumen (efecto inverso)."""

    async def _undo_volume(payload: Dict[str, Any]) -> str:
        import shutil
        skill = SystemSkill()
        backend = "pactl" if shutil.which("pactl") else "wpctl"
        percent = int(payload.get("percent", 5))
        up = payload.get("direction", "up") == "up"
        await skill._volume_cmd(backend, percent, up=up)
        return "Volumen restaurado."

    audit.register_undo("volume_step", _undo_volume)
