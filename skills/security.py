#!/usr/bin/env python3
"""
Higiene y defensa del PROPIO equipo (nunca ataque).

- "auditoría de seguridad" -> pack + nivel de riesgo bajo/medio/alto
- "puertos abiertos", "conexiones", "firewall", "procesos sospechosos",
  "revisa el ssh", "permisos peligrosos", "actualizaciones",
  "login fallidos", "baseline", "verifica integridad", "escanea virus",
  "consejos de endurecimiento"
- Pedidos ofensivos -> rechazo explícito.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

from core import security_ops as sec
from skills.base import Skill

logger = logging.getLogger(__name__)

REFUSAL = ("Solo puedo ayudarte a proteger este equipo, "
           "no a atacar otros sistemas.")

_OFFENSIVE = (
    "hackea", "hackear", "hackeado", "keylogger", "keylog",
    "mitm", "hydra", "sqlmap", "metasploit", "burp",
    "fuerza bruta", "credential stuffing", "phishing",
    "wifi del vecino", "wifi ajeno", "contraseña del vecino",
    "romper contraseña", "romper clave", "robar contraseña",
    "ataca", "atacar", "ataque a", "ddos", "denegación",
    "bypass", "saltarse la autenticación", "ransomware", "troyano",
)


def is_offensive_request(text: str) -> bool:
    """True si pide atacar/explotar terceros. Usado por el router."""
    low = text.lower()
    return any(w in low for w in _OFFENSIVE)

_SENSITIVE_PORTS = {"22", "3389", "5900", "445", "21", "23"}


class SecuritySkill(Skill):
    """Auditoría defensiva local."""

    patterns = [
        "auditoría de seguridad", "auditoria de seguridad",
        "revisa la seguridad", "security check", "security audit",
        "chequeo de seguridad",
        "qué puertos tengo abiertos", "que puertos tengo abiertos",
        "puertos abiertos", "puertos escuchando",
        "conexiones de red", "conexiones establecidas",
        "estado del firewall", "firewall",
        "procesos sospechosos", "proceso raro",
        "revisa el ssh", "audita el ssh",
        "permisos peligrosos",
        "actualizaciones de seguridad", "hay actualizaciones",
        "intentos de login fallidos", "login fallidos", "logins fallidos",
        "crea baseline de integridad", "crear baseline", "baseline",
        "verifica integridad", "verificar integridad", "integridad",
        "escanea virus", "escanear virus", "antivirus",
        "consejos de endurecimiento", "endurecer", "cómo me protejo",
        "como me protejo", "modo seguro",
    ]

    intent = "security"

    # Inyectado en main.py (y gui_server.py)
    config = None

    def _cfg(self, key: str, default):
        try:
            return (self.config.get(f"security.{key}", default)
                    if self.config else default)
        except Exception:
            return default

    # -- entry --------------------------------------------------------------
    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        low = text.lower()
        if any(w in low for w in _OFFENSIVE):
            return {"response": REFUSAL, "silent": False, "no_audit": True}

        if "firewall" in low and any(
                w in low for w in ("activa", "habilita", "enciende", "prende")):
            return await self._firewall_change()
        wants_verify = "verifica" in low or (
            "integridad" in low and "crea" not in low and "crear" not in low)
        wants_create = ("crea baseline" in low or "crear baseline" in low
                        or ("baseline" in low and not wants_verify))
        if wants_create:
            return await self._baseline_create()
        if wants_verify:
            return await self._baseline_verify()
        if "auditor" in low or "chequeo" in low or "revisa la seguridad" in low \
                or "security" in low or "modo seguro" in low:
            return await self._full_audit()
        if "puerto" in low:
            return await self._ports()
        if "conexion" in low or "conexión" in low:
            return await self._conns()
        if "firewall" in low:
            return await self._firewall()
        if "proceso" in low:
            return await self._procs()
        if "ssh" in low:
            return await self._ssh()
        if "permiso" in low:
            return await self._perms()
        if "actualiza" in low:
            return await self._updates()
        if "login" in low:
            return await self._logins()
        if "virus" in low or "antivirus" in low or "escanea" in low:
            return await self._scan(low)
        if "endurec" in low or "protejo" in low or "consejo" in low:
            return await self._harden()
        return {"response": "Pide auditoría, puertos, firewall, ssh o integridad.",
                "silent": False, "no_audit": True}

    def _audit(self, action: str, result: str) -> Dict[str, Any]:
        return {"response": result, "silent": False,
                "audit_action": f"security:{action}"}

    # -- checks ---------------------------------------------------------------
    async def _full_audit(self) -> Dict[str, Any]:
        fw = await sec.firewall_status()
        ports = await sec.list_listening_ports(
            limit=int(self._cfg("max_ports_listed", 15)))
        upd = await sec.check_updates()
        ssh = await sec.ssh_config_audit()
        exposed = [p for p in ports
                   if p.get("addr") in ("0.0.0.0", "::", "*")
                   and p.get("port") in _SENSITIVE_PORTS]
        level, reasons = self._risk(fw, ports, upd, ssh, exposed)
        parts = [f"Riesgo {level}."]
        parts.append("Firewall " + ("activo." if fw.get("active")
                                    else "APAGADO o ausente."))
        parts.append(f"{len(ports)} puertos escuchando"
                     + (f" (expuestos sensibles: {', '.join(p['port'] for p in exposed)})."
                        if exposed else "."))
        pend = upd.get("pending", -1)
        if pend is not None and pend >= 0:
            parts.append("Al día." if pend == 0 else f"{pend} updates pendientes.")
        if reasons:
            parts.append("Ver: " + "; ".join(reasons[:2]) + ".")
        return self._audit("audit", " ".join(parts))

    @staticmethod
    def _risk(fw, ports, upd, ssh, exposed) -> tuple[str, List[str]]:
        reasons: List[str] = []
        score = 0
        if not fw.get("active"):
            score += 2
            reasons.append("enciende el firewall")
        if exposed:
            score += 2
            reasons.append("cierra puertos sensibles a 0.0.0.0")
        pend = upd.get("pending", -1)
        if isinstance(pend, int) and pend > 20:
            score += 1
            reasons.append("actualiza el sistema")
        weak_ssh = any("PasswordAuthentication yes" in s or "PermitRootLogin yes" in s
                       for s in ssh)
        if weak_ssh:
            score += 1
            reasons.append("endurece el SSH")
        if len(ports) > 10:
            score += 1
            reasons.append("revisa servicios innecesarios")
        if score >= 3:
            return "ALTO", reasons
        if score >= 1:
            return "MEDIO", reasons
        return "BAJO", reasons

    async def _ports(self) -> Dict[str, Any]:
        ports = await sec.list_listening_ports(
            limit=int(self._cfg("max_ports_listed", 15)))
        if not ports:
            return self._audit("ports", "Sin puertos a la escucha o sin ss.")
        items = [f"{p['port']}/{p['process'] or '?'}" for p in ports[:8]]
        extra = f" (+{len(ports) - 8} más)" if len(ports) > 8 else ""
        return self._audit("ports", f"Escuchando: {', '.join(items)}{extra}.")

    async def _conns(self) -> Dict[str, Any]:
        conns = await sec.list_established_connections(limit=8)
        if not conns:
            return self._audit("conns", "Sin conexiones establecidas ahora.")
        items = [f"{c['remote']} ({c['process'] or '?'})" for c in conns[:5]]
        return self._audit("conns", "Activas: " + "; ".join(items) + ".")

    async def _firewall(self) -> Dict[str, Any]:
        fw = await sec.firewall_status()
        if fw.get("active"):
            return self._audit("firewall", f"Firewall activo ({fw['tool']}).")
        return self._audit("firewall",
                           "Firewall apagado o ausente. Di 'activa el firewall' para encenderlo (pide confirma).")

    async def _firewall_change(self) -> Dict[str, Any]:
        if not self._cfg("allow_firewall_changes", False):
            return {"response": "Cambiar el firewall está desactivado "
                                "(security.allow_firewall_changes).",
                    "silent": False}
        import shutil

        async def _enable():
            from utils.safe_subprocess import run_shell
            if shutil.which("ufw"):
                rc, _, _ = await run_shell("ufw --force enable", timeout=15.0)
                ok = rc == 0
            else:
                ok = False
            return {"response": "Firewall activado." if ok else
                    "No pude activar el firewall (suele pedir sudo).",
                    "silent": False, "audit_action": "security:firewall-on"}
        return {"response": "Vas a activar el firewall. Di confirma o cancela.",
                "silent": False, "requires_confirmation": True,
                "deferred_execute": _enable,
                "audit_action": "security:firewall-on?"}

    async def _procs(self) -> Dict[str, Any]:
        procs = await sec.list_suspicious_processes(
            limit=int(self._cfg("max_processes_listed", 8)))
        if not procs:
            return self._audit("procs", "Nada sospechoso a simple vista.")
        items = [f"{p['comm']} (pid {p['pid']}: {p['reason']})" for p in procs[:4]]
        return self._audit("procs",
                           "Ojo con: " + "; ".join(items) + ". Revísalos manualmente.")

    async def _ssh(self) -> Dict[str, Any]:
        findings = await sec.ssh_config_audit()
        return self._audit("ssh", "SSH: " + " ".join(findings[:3]))

    async def _perms(self) -> Dict[str, Any]:
        files = await sec.world_writable_in_home(limit=20)
        if not files:
            return self._audit("perms", "Sin ficheros world-writable en tu home (4 niveles).")
        shown = ", ".join(f.split(os.path.expanduser("~") + "/")[-1]
                          for f in files[:5])
        extra = f" (+{len(files) - 5})" if len(files) > 5 else ""
        return self._audit("perms", f"Revisa permisos en: {shown}{extra}.")

    async def _updates(self) -> Dict[str, Any]:
        upd = await sec.check_updates()
        pend = upd.get("pending", -1)
        if pend is None or pend < 0:
            return self._audit("updates", "No pude contar actualizaciones.")
        if pend == 0:
            return self._audit("updates", "Sistema al día.")
        return self._audit("updates", f"{pend} actualizaciones pendientes ({upd.get('tool')}).")

    async def _logins(self) -> Dict[str, Any]:
        fails = await sec.failed_logins(limit=5)
        if not fails:
            return self._audit("logins", "Sin intentos fallidos recientes visibles.")
        return self._audit("logins", f"Fallidos recientes: {fails[0][:120]}.")

    async def _baseline_create(self) -> Dict[str, Any]:
        paths = self._cfg("baseline_paths",
                          ["~/.ssh", "~/.bashrc", "~/.config"])
        try:
            import asyncio as _aio
            path = await _aio.to_thread(sec.baseline_save, list(paths))
            import json
            n = len(json.loads(path.read_text(encoding="utf-8")).get("files", {}))
            return self._audit("baseline-save", f"Baseline con {n} ficheros.")
        except Exception as e:
            logger.error("Baseline falló: %s", e)
            return {"response": "No pude crear el baseline.", "silent": False}

    async def _baseline_verify(self) -> Dict[str, Any]:
        import asyncio as _aio
        diff = await _aio.to_thread(sec.baseline_diff)
        if diff == ["SIN_BASELINE"]:
            return {"response": "Sin baseline. Di 'crea baseline de integridad'.",
                    "silent": False}
        if diff == ["BASELINE_CORRUPTO"]:
            return {"response": "Baseline corrupto; créalo de nuevo.", "silent": False}
        if not diff:
            return self._audit("baseline-verify", "Integridad intacta.")
        shown = "; ".join(diff[:3])
        extra = f" (+{len(diff) - 3})" if len(diff) > 3 else ""
        return self._audit("baseline-verify", f"Cambios: {shown}{extra}.")

    async def _scan(self, low: str) -> Dict[str, Any]:
        if not sec.clamav_available():
            return {"response": "ClamAV no instalado (sudo apt install clamav).",
                    "silent": False}
        m = re.search(r"escanea(?:?:r)?(?:?: virus)? en ([\w~/.\- ]+)", low)
        target = (m.group(1).strip() if m else None) or \
            str(self._cfg("clamav_default_path", "~/Downloads"))
        res = await sec.clamav_scan(target)
        if res.get("infected"):
            return self._audit("clamav", f"¡Infección en {target}! {res['detail'][:200]}")
        return self._audit("clamav", res.get("detail", "Escaneo terminado.")[:300])

    async def _harden(self) -> Dict[str, Any]:
        tips: List[str] = []
        fw = await sec.firewall_status()
        if not fw.get("active"):
            tips.append("enciende el firewall")
        ssh = await sec.ssh_config_audit()
        if any("yes" in s for s in ssh if "PasswordAuthentication" in s or "PermitRootLogin" in s):
            tips.append("SSH solo con claves")
        upd = await sec.check_updates()
        if isinstance(upd.get("pending"), int) and upd["pending"] > 0:
            tips.append("aplica actualizaciones")
        tips += ["usa sudo en vez de root", "revisa 'permisos peligrosos'"]
        return self._audit("harden", "Prioridades: " + "; ".join(tips[:5]) + ".")
