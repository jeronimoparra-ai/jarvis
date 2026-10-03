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
        "suspende", "suspender", "información del sistema", "estado del sistema"
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
            
        # Shutdown (alto riesgo: pide confirmación explícita)
        if "apaga" in text_lower:
            if "confirma" not in text_lower and "confirmo" not in text_lower:
                return {"response": "Vas a apagar el equipo. Di 'apaga, confirma' para hacerlo.",
                        "silent": False, "requires_confirmation": True}
            await self._system_command("systemctl poweroff")
            return {"response": "Apagando.", "silent": False}

        # Restart (alto riesgo)
        if "reinicia" in text_lower or "reiniciar" in text_lower:
            if "confirma" not in text_lower and "confirmo" not in text_lower:
                return {"response": "Vas a reiniciar el equipo. Di 'reinicia, confirma' para hacerlo.",
                        "silent": False, "requires_confirmation": True}
            await self._system_command("systemctl reboot")
            return {"response": "Reiniciando.", "silent": False}

        # Suspend (riesgo medio: también confirma)
        if "suspende" in text_lower or "suspender" in text_lower:
            if "confirma" not in text_lower and "confirmo" not in text_lower:
                return {"response": "Vas a suspender el equipo. Di 'suspende, confirma' para hacerlo.",
                        "silent": False, "requires_confirmation": True}
            await self._system_command("systemctl suspend")
            return {"response": "Suspendiendo.", "silent": False}
            
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
            if shutil.which("pactl") is None:
                return {"response": "Control de volumen no disponible (falta pactl).",
                        "silent": False}
            # Determine direction
            if "subir" in text or "sube" in text or "aumentar" in text or "aumenta" in text:
                if "mute" in text or "silencio" in text:
                    await self._system_command("pactl set-sink-mute @DEFAULT_SINK@ toggle")
                    return {"response": "Volumen silenciado.", "silent": False}
                await self._system_command(f"pactl set-sink-volume @DEFAULT_SINK@ +{percent}%")
                return {"response": "", "silent": True}

            elif "bajar" in text or "baja" in text or "reducir" in text or "reduce" in text:
                await self._system_command(f"pactl set-sink-volume @DEFAULT_SINK@ -{percent}%")
                return {"response": "", "silent": True}
                
            elif "mute" in text or "silencio" in text:
                await self._system_command("pactl set-sink-mute @DEFAULT_SINK@ toggle")
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
