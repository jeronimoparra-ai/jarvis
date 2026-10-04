#!/usr/bin/env python3
"""
Operaciones defensivas LOCALES (solo este equipo, solo lectura salvo
acciones explícitas con pending).

Sin dependencias pesadas: stdlib + CLIs del sistema (ss, ufw, clamscan...).
Todo best-effort con timeouts duros: nunca crash, nunca cuelgues.
En Windows: PowerShell equivalente donde existe.

PROHIBIDO aquí: escaneo externo, exploits, fuerza bruta, MITM, keyloggers.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.platform import IS_WINDOWS

logger = logging.getLogger(__name__)

SEC_DIR = Path.home() / ".local" / "share" / "jarvis" / "security"


async def _sh(cmd: str, timeout: float = 10.0) -> tuple[int, str]:
    from utils.safe_subprocess import run_shell
    rc, out, _ = await run_shell(cmd, timeout=timeout)
    return rc, out


# ---------------------------------------------------------- inventario local

async def list_listening_ports(limit: int = 15) -> List[Dict[str, Any]]:
    """Puertos LISTEN de ESTE host (puerto, dirección, proceso, pid)."""
    out: List[Dict[str, Any]] = []
    if IS_WINDOWS:
        rc, txt = await _sh(
            'powershell -NoProfile -Command '
            '"Get-NetTCPConnection -State Listen | '
            'Select-Object LocalAddress,LocalPort,OwningProcess | '
            'Format-Table -HideTableHeaders | Out-String"')
        if rc == 0:
            for line in txt.splitlines()[:limit]:
                parts = line.split()
                if len(parts) >= 3:
                    out.append({"addr": parts[0], "port": parts[1],
                                "pid": parts[2], "process": ""})
        return out
    cmd = None
    if shutil.which("ss"):
        cmd = "ss -tulpnH"
    elif shutil.which("netstat"):
        cmd = "netstat -tulpn"
    if cmd is None:
        return out
    rc, txt = await _sh(cmd, timeout=8.0)
    if rc != 0:
        return out
    for line in txt.splitlines()[:limit * 2]:
        m = re.search(r"(LISTEN)\s+\S+\s+(\S+):(\d+)", line)
        if not m:
            m = re.search(r"tcp\S*\s+\S+\s+(\S+):(\d+).*LISTEN", line)
            if not m:
                continue
        addr, port = (m.group(2), m.group(3)) if m.lastindex == 3 else (m.group(1), m.group(2))
        proc, pid = "", ""
        pm = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        if pm:
            proc, pid = pm.group(1), pm.group(2)
        else:
            pm = re.search(r"(\d+)/(\S+)", line)
            if pm:
                pid, proc = pm.group(1), pm.group(2)
        out.append({"addr": addr, "port": port, "process": proc, "pid": pid})
        if len(out) >= limit:
            break
    return out


async def list_established_connections(limit: int = 10) -> List[Dict[str, str]]:
    """Conexiones ESTABLISHED de este host (remoto, proceso)."""
    out: List[Dict[str, str]] = []
    if IS_WINDOWS:
        rc, txt = await _sh(
            'powershell -NoProfile -Command '
            '"Get-NetTCPConnection -State Established | '
            'Select-Object RemoteAddress,RemotePort,OwningProcess | '
            'Format-Table -HideTableHeaders | Out-String"')
        if rc == 0:
            for line in txt.splitlines()[:limit]:
                parts = line.split()
                if len(parts) >= 2:
                    out.append({"remote": f"{parts[0]}:{parts[1]}",
                                "process": parts[2] if len(parts) > 2 else ""})
        return out
    cmd = "ss -tunapH state established" if shutil.which("ss") else None
    if cmd is None and shutil.which("netstat"):
        cmd = "netstat -tunap"
    if cmd is None:
        return out
    rc, txt = await _sh(cmd, timeout=8.0)
    if rc != 0:
        return out
    for line in txt.splitlines():
        if "ESTAB" not in line:
            continue
        remote, proc = "", ""
        m = re.search(r"ESTAB\s+\S+\s+\S+\s+(\S+)", line)
        if m:
            remote = m.group(1)
        pm = re.search(r'users:\(\("([^"]+)"', line)
        if pm:
            proc = pm.group(1)
        out.append({"remote": remote, "process": proc})
        if len(out) >= limit:
            break
    return out


async def list_suspicious_processes(limit: int = 8) -> List[Dict[str, str]]:
    """Heurística simple: procesos en /tmp, nombres raros, cpu alto."""
    found: List[Dict[str, str]] = []
    if IS_WINDOWS:
        return found  # best-effort: sin heurística fiable sin firmas
    rc, txt = await _sh(
        "ps -eo pid,pcpu,comm,args --sort=-%cpu | head -30", timeout=8.0)
    if rc != 0:
        return found
    for line in txt.splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, cpu, comm, args = parts
        reasons = []
        if args.startswith(("/tmp/", "/dev/shm/", "/var/tmp/")):
            reasons.append("ejecutable en dir temporal")
        if re.search(r"^\.?[a-z]{1,2}$|miner|xmrig|kdevtmp|kinsing", comm):
            reasons.append("nombre sospechoso")
        try:
            if float(cpu) > 80:
                reasons.append(f"CPU {cpu}%")
        except ValueError:
            pass
        if reasons:
            found.append({"pid": pid, "comm": comm,
                          "reason": ", ".join(reasons)})
        if len(found) >= limit:
            break
    return found


async def list_local_users() -> List[str]:
    """Usuarios con shell interactiva (Linux) / locales (Windows)."""
    if IS_WINDOWS:
        rc, txt = await _sh(
            'powershell -NoProfile -Command '
            '"Get-LocalUser | Select-Object -ExpandProperty Name"')
        return [u for u in txt.splitlines() if u.strip()][:20] if rc == 0 else []
    users = []
    try:
        with open("/etc/passwd", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) > 6 and parts[6].strip() in (
                        "/bin/bash", "/bin/sh", "/bin/zsh", "/bin/fish"):
                    users.append(parts[0])
    except OSError:
        pass
    return users[:20]


# ------------------------------------------------------- superficie de ataque

async def firewall_status() -> Dict[str, Any]:
    """Estado del firewall local."""
    if IS_WINDOWS:
        rc, txt = await _sh(
            'powershell -NoProfile -Command '
            '"(Get-NetFirewallProfile -PolicyStore ActiveStore | '
            'Select-Object Name,Enabled | Out-String).Trim()"')
        return {"tool": "windows-firewall", "detail": txt[:300] if rc == 0 else ""}
    if shutil.which("ufw"):
        rc, txt = await _sh("ufw status", timeout=8.0)
        if rc == 0:
            active = "active" in txt.lower().splitlines()[0] if txt else False
            return {"tool": "ufw", "active": active,
                    "detail": "\n".join(txt.splitlines()[:8])}
    if shutil.which("firewall-cmd"):
        rc, txt = await _sh("firewall-cmd --state", timeout=8.0)
        return {"tool": "firewalld",
                "active": txt.strip().lower() == "running", "detail": txt[:200]}
    return {"tool": "none", "active": False, "detail": "sin firewall detectado"}


async def ssh_config_audit() -> List[str]:
    """Solo lectura de sshd_config. Lista de hallazgos (vacía = bien o N/A)."""
    findings: List[str] = []
    if IS_WINDOWS:
        return ["SSH server no aplica en este Windows (revisa OpenSSH si lo instalaste)."]
    path = Path("/etc/ssh/sshd_config")
    if not path.exists():
        return ["Sin servidor SSH instalado (nada que auditar)."]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["No se pudo leer sshd_config (permiso denegado)."]
    active = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            active[parts[0].lower()] = parts[1].lower()
    if active.get("permitrootlogin", "prohibit-password") in ("yes",):
        findings.append("PermitRootLogin yes: permite root por SSH (riesgo).")
    if active.get("passwordauthentication", "yes") == "yes":
        findings.append("PasswordAuthentication yes: considera solo claves.")
    if active.get("protocol", "2") != "2":
        findings.append("Protocol distinto de 2 (obsoleto).")
    if not findings:
        findings.append("SSH bien configurado (root limitado, protocolo 2).")
    return findings


async def world_writable_in_home(limit: int = 50) -> List[str]:
    """Ficheros world-writable en $HOME (acotado, timeout duro)."""
    if IS_WINDOWS:
        return []
    rc, txt = await _sh(
        f"find {Path.home()} -maxdepth 4 -type f -perm -o+w 2>/dev/null | head -{limit}",
        timeout=12.0)
    return [l for l in txt.splitlines() if l.strip()][:limit] if rc == 0 else []


async def suid_binaries(limit: int = 30) -> List[str]:
    """Binarios SUID en rutas del sistema (acotado). Solo Linux."""
    if IS_WINDOWS:
        return []
    rc, txt = await _sh(
        "find /usr/bin /usr/sbin /bin /sbin -maxdepth 2 -perm -4000 "
        f"2>/dev/null | head -{limit}", timeout=12.0)
    return [l for l in txt.splitlines() if l.strip()][:limit] if rc == 0 else []


# ------------------------------------------------------------------- higiene

async def check_updates() -> Dict[str, Any]:
    """Actualizaciones pendientes (solo consulta, nunca instala)."""
    if IS_WINDOWS:
        return {"tool": "winget", "pending": -1,
                "detail": "revisa Windows Update manualmente"}
    if shutil.which("apt-get"):
        rc, txt = await _sh(
            "apt-get -s upgrade 2>/dev/null | grep -c '^Inst'", timeout=60.0)
        try:
            return {"tool": "apt", "pending": int(txt.strip()),
                    "detail": ""}
        except ValueError:
            pass
    for mgr, cmd in (("dnf", "dnf check-update -q | wc -l"),
                     ("pacman", "checkupdates | wc -l")):
        if shutil.which(mgr):
            rc, txt = await _sh(cmd, timeout=60.0)
            try:
                return {"tool": mgr, "pending": int(txt.strip()), "detail": ""}
            except ValueError:
                pass
    return {"tool": "none", "pending": -1, "detail": "sin gestor conocido"}


async def failed_logins(limit: int = 20) -> List[str]:
    """Últimos logins fallidos si hay logs legibles."""
    if IS_WINDOWS:
        rc, txt = await _sh(
            'powershell -NoProfile -Command '
            '"Get-WinEvent -FilterHashtable @{LogName=\'Security\';ID=4625} '
            '-MaxEvents 5 -ErrorAction SilentlyContinue | '
            'Select-Object -ExpandProperty Message"')
        return [txt[:200]] if rc == 0 and txt else []
    for cmd in ("journalctl -u sshd --since '7 days ago' --no-pager -p warning "
                f"| grep -i fail | tail -{limit}",
                f"grep -i 'failed password' /var/log/auth.log 2>/dev/null | tail -{limit}"):
        rc, txt = await _sh(cmd, timeout=10.0)
        if rc == 0 and txt.strip():
            return [l.split("]:", 1)[-1].strip()[:160] for l in txt.splitlines()
                    if l.strip()][:limit]
    return []


# ---------------------------------------------------------------- integridad

def hash_file(path: str) -> str:
    """SHA256 de un fichero. '' si no se puede leer."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _iter_files(paths: List[str]):
    for raw in paths:
        base = Path(os.path.expanduser(raw))
        if base.is_file():
            yield str(base)
        elif base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file() and not p.is_symlink():
                    try:
                        if p.stat().st_size < 5_000_000:
                            yield str(p)
                    except OSError:
                        continue


def baseline_path() -> Path:
    SEC_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    return SEC_DIR / "baseline.json"


def baseline_save(paths: List[str]) -> Path:
    """Guarda hashes de rutas. Devuelve la ruta del baseline."""
    data = {"created": datetime.now().isoformat(), "files": {}}
    for f in _iter_files(paths):
        digest = hash_file(f)
        if digest:
            data["files"][f] = digest
    path = baseline_path()
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    logger.info("Baseline guardado: %d ficheros", len(data["files"]))
    return path


def baseline_diff() -> List[str]:
    """Compara contra el baseline. [] si no hay cambios o no hay baseline."""
    path = baseline_path()
    if not path.exists():
        return ["SIN_BASELINE"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["BASELINE_CORRUPTO"]
    changed = []
    for f, old in data.get("files", {}).items():
        new = hash_file(f)
        if not new:
            changed.append(f"desaparecido: {f}")
        elif new != old:
            changed.append(f"modificado: {f}")
    return changed


# ----------------------------------------------------------------- antivirus

def clamav_available() -> bool:
    return shutil.which("clamscan") is not None and not IS_WINDOWS


async def clamav_scan(path: str, timeout: float = 300.0) -> Dict[str, Any]:
    """Escanea una ruta con clamscan (solo si existe)."""
    if not clamav_available():
        return {"ok": False,
                "detail": "ClamAV no instalado (sudo apt install clamav)."}
    target = os.path.expanduser(path)
    if not os.path.exists(target):
        return {"ok": False, "detail": f"No existe: {path}"}
    rc, txt = await _sh(f"clamscan -r -i '{target}'", timeout=timeout)
    tail = "\n".join(txt.splitlines()[-6:])
    if rc == 0:
        return {"ok": True, "infected": 0, "detail": tail or "Limpio."}
    if rc == 1:
        return {"ok": True, "infected": 1, "detail": tail}
    return {"ok": False, "detail": tail or "Error de clamscan."}


# ------------------------------------------------------- red local (opt-in)

def is_local_target(target: str) -> bool:
    """True solo para 127.0.0.1/localhost o IP propia (nunca terceros)."""
    t = target.strip().lower()
    if t in ("127.0.0.1", "localhost", "::1"):
        return True
    import socket
    try:
        own_ips = {ip for ip in socket.gethostbyname_ex(
            socket.gethostname())[2]}
    except OSError:
        own_ips = set()
    try:
        return socket.gethostbyname(t) in own_ips
    except OSError:
        return False
