#!/usr/bin/env python3
"""
Estado rico del sistema (complementa a system.py, no lo sustituye).

- CPU load, RAM %, disco home, batería, temperatura, top procesos
- "hay actualizaciones" -> check ligero apt-get -s upgrade

Frases: estado del pc, batería, uso de cpu, espacio en disco,
qué consume / qué está consumiendo, temperatura.
Respuesta breve en 1-2 frases.
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from skills.base import Skill

logger = logging.getLogger(__name__)


class StatusSkill(Skill):
    """Foto rápida del estado de la máquina."""

    patterns = [
        "estado del pc", "estado del equipo", "cómo está el pc",
        "como está el pc", "batería", "bateria", "uso de cpu",
        "uso de memoria", "espacio en disco", "disco libre",
        "qué consume", "que consume", "qué está consumiendo",
        "temperatura", "hay actualizaciones", "actualizaciones",
    ]

    intent = "status"

    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        low = text.lower()
        if "actualiza" in low:
            return {"response": await self._updates(), "silent": False}
        if "bater" in low:
            return {"response": await self._battery(), "silent": False}
        if "cpu" in low or "consume" in low or "memoria" in low:
            return {"response": await self._load(), "silent": False}
        if "disco" in low or "espacio" in low:
            return {"response": await self._disk(), "silent": False}
        if "temperatura" in low:
            return {"response": await self._temp(), "silent": False}
        # "estado del pc": resumen en 2 frases
        parts = [await self._load(), await self._battery()]
        summary = " ".join(p for p in parts if p and "Error" not in p)
        return {"response": summary or "No pude leer el estado.", "silent": False}

    async def _sh(self, cmd: str, timeout: float = 8.0) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return out.decode(errors="replace").strip()
        except Exception as e:
            logger.debug("status '%s' falló: %s", cmd, e)
            return ""

    async def _load(self) -> str:
        try:
            load1, _, _ = os.getloadavg()
            ncpu = os.cpu_count() or 1
            mem = await self._sh("free | awk '/Mem:/ {printf \"%d\", $3/$2*100}'")
            top = await self._sh(
                "ps -eo comm,%cpu --sort=-%cpu | awk 'NR==2 {print $1\" \"$2\"%\"}'")
            msg = f"CPU {load1:.1f} de {ncpu} núcleos"
            if mem:
                msg += f", RAM {mem}%"
            if top:
                msg += f". Top: {top}"
            return msg + "."
        except Exception:
            return "Error leyendo carga."

    async def _battery(self) -> str:
        base = Path("/sys/class/power_supply")
        try:
            for bat in sorted(base.glob("BAT*")):
                cap = (bat / "capacity").read_text().strip()
                status = (bat / "status").read_text().strip()
                return f"Batería {cap}%, {status}."
        except OSError:
            pass
        return "Sin batería (sobremesa)."

    async def _disk(self) -> str:
        try:
            st = os.statvfs(str(Path.home()))
            free_gb = st.f_bavail * st.f_frsize / 1e9
            total_gb = st.f_blocks * st.f_frsize / 1e9
            used = 100 * (1 - st.f_bavail / st.f_blocks)
            return f"Disco home: {free_gb:.0f} de {total_gb:.0f} GB libres ({used:.0f}% usado)."
        except OSError:
            return "Error leyendo disco."

    async def _temp(self) -> str:
        for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
            try:
                kind = (zone / "type").read_text().strip()
                millic = int((zone / "temp").read_text().strip())
                if millic > 0:
                    return f"Temperatura ({kind}): {millic / 1000:.0f}°C."
            except (OSError, ValueError):
                continue
        out = await self._sh("sensors 2>/dev/null | grep -m1 -oP '\\+\\d+\\.\\d+°C'")
        return f"Temperatura: {out}." if out else "Sin sensor térmico legible."

    async def _updates(self) -> str:
        if shutil.which("apt-get") is None:
            return "Sin apt-get para comprobar."
        out = await self._sh(
            "apt-get -s upgrade 2>/dev/null | grep -c '^Inst'", timeout=60.0)
        try:
            n = int(out)
        except ValueError:
            return "No pude comprobar actualizaciones."
        if n == 0:
            return "Todo actualizado."
        return f"Hay {n} actualizaciones pendientes."
