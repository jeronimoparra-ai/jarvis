#!/usr/bin/env python3
"""
Terminal command execution skill for Jarvis

Handles:
- Executing validated terminal commands
- Safety validation to prevent dangerous operations

Commands recognized:
- "ejecuta ls -la"
- "corre git status"
- "ejecuta find /home -name *.py"

Seguridad: whitelist directa, confirmación con "confirma" para comandos
sensibles y bloqueo absoluto de destructivos (mkfs, dd, borrado de /).
"""

import asyncio
import logging
import re
import shlex
from typing import Dict, Any, Optional, List

from skills.base import Skill

logger = logging.getLogger(__name__)

class TerminalSkill(Skill):
    """Ejecución de comandos de terminal"""
    
    patterns = [
        "ejecuta", "ejecutar", "corre", "correr", 
        "comando", "terminal", "/bin/"
    ]
    
    intent = "terminal"
    
    # Comandos siempre bloqueados (destructivos sin recuperación)
    ALWAYS_BLOCKED = [
        "mkfs", "dd", "format", ":(){:|:&};:",
    ]

    # Comandos peligrosos: solo con "confirma" explícito
    DANGEROUS_COMMANDS = [
        "rm", "rmdir", "del",
        "shutdown", "reboot", "halt", "poweroff",
        "chmod", "chown", "chgrp",
        "killall", "kill", "pkill",
        "mv", "cp",
    ]

    # Comandos seguros: ejecución directa sin confirmación
    SAFE_WHITELIST = [
        "ls", "pwd", "whoami", "date", "uptime", "free", "df",
        "echo", "cat", "grep", "find", "ps", "top", "uname",
        "git", "python3", "pip", "lsblk", "du",
        # Defensivos de solo lectura (auditoría local)
        "ss", "clamscan",
    ]

    # Herramientas ofensivas: siempre bloqueadas (nunca pentest externo)
    OFFENSIVE_BLOCKED = [
        "hydra", "sqlmap", "msfconsole", "msfvenom", "john",
        "aircrack-ng", "hashcat", "ettercap", "nikto", "theharvester",
    ]

    # Comandos con subcomandos restringidos a solo-lectura
    READONLY_SUBCOMMANDS = {
        "ufw": ("status",),
        "systemctl": ("is-active", "status", "is-enabled"),
    }
    
    # Command aliases
    COMMAND_ALIASES = {
        "corre": "ejecuta",
        "correr": "ejecuta",
        "comando": "ejecuta",
        "terminal": "ejecuta",
    }
    
    def __init__(self):
        super().__init__()
        self.silent = False
        
    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a terminal command
        
        Args:
            text: User command text
            intent: Intent classification (optional)
            
        Returns:
            Dict with response
        """
        text_lower = text.lower().strip()
        
        # Extract command (y quita el sufijo de confirmación)
        command = self._extract_command(text_lower)
        if not command:
            return {"response": "No reconozco el comando.", "silent": False}
        command = re.sub(r"[,.\s]*(confirma|confirmo|confirmado)\s*$", "", command).strip()
        if not command:
            return {"response": "No reconozco el comando.", "silent": False}
            
        # Validate command safety
        validation = self._validate_command(command)
        if validation.get("blocked"):
            return {"response": f"Comando bloqueado: {validation['reason']}",
                    "silent": False}
        if validation.get("needs_confirmation"):
            if "confirma" not in text_lower and "confirmo" not in text_lower:
                return {"response": f"Comando sensible ({validation['reason']}). "
                                     f"Di '{command}, confirma' para ejecutarlo.",
                        "silent": False, "requires_confirmation": True}
        if not validation["safe"]:
            return {"response": f"Comando restringido: {validation['reason']}",
                    "silent": False}
            
        # Execute command
        result = await self._run_command(command)
        
        if result['success']:
            # For most commands, return truncated output
            output = result['output']
            if len(output) > 500:
                output = output[:500] + "..."
                
            if output:
                return {"response": output, "silent": False}
            return {"response": "", "silent": True}
        else:
            return {"response": f"Error: {result['error']}", "silent": False}
            
    def _extract_command(self, text: str) -> Optional[str]:
        """
        Extract command from text
        
        Args:
            text: Lowercase user text
            
        Returns:
            Command string or None
        """
        # Match patterns like "ejecuta ls -la"
        for pattern in ["ejecuta", "ejecutar", "corre", "correr", "comando", "terminal"]:
            if text.startswith(pattern):
                return text[len(pattern):].strip()
                
        # If no keyword prefix, check if it looks like a command
        if re.match(r'^[a-z_][a-z0-9_-]*\s', text) or text.startswith('/'):
            return text
            
        return None
        
    def _validate_command(self, command: str) -> Dict[str, Any]:
        """Valida seguridad. Claves: safe, blocked, needs_confirmation, reason."""
        parts = command.split()
        base_cmd = parts[0].split('/')[-1] if parts else ""

        # Bloqueo absoluto: borrado masivo / formateo / fork-bomb
        if base_cmd in self.ALWAYS_BLOCKED:
            return {"safe": False, "blocked": True,
                    "reason": f"'{base_cmd}' está prohibido"}
        # Herramientas ofensivas: nunca (ni con confirma)
        if base_cmd in self.OFFENSIVE_BLOCKED:
            return {"safe": False, "blocked": True,
                    "reason": f"'{base_cmd}' es herramienta ofensiva"}
        # nmap: solo localhost con confirma; externo siempre bloqueado
        if base_cmd == "nmap":
            import re as _re
            targets = [p for p in parts[1:]
                       if not p.startswith("-")
                       and (_re.search(r"[.:]", p) or p.isalpha())]
            from core.security_ops import is_local_target
            if targets and all(is_local_target(t) for t in targets):
                return {"safe": True, "needs_confirmation": True,
                        "reason": "escaneo solo localhost"}
            return {"safe": False, "blocked": True,
                    "reason": "escaneo externo prohibido"}
        if base_cmd == "rm" and any(t in parts for t in ("/", "/*", "/home", "~")):
            return {"safe": False, "blocked": True,
                    "reason": "borrado de rutas críticas"}
        if re.search(r":\(\)\s*\{\s*:\|\:&\s*\}\s*;", command):
            return {"safe": False, "blocked": True, "reason": "fork-bomb"}

        # Patrones de inyección / encadenado: piden confirmación
        risky_patterns = [r";", r"&&", r"\|\|", r"\$\(", r"`", r">>", r"\|"]
        for pat in risky_patterns:
            if re.search(pat, command):
                return {"safe": True, "needs_confirmation": True,
                        "reason": "encadenado/redirección de shell"}

        # Comandos peligrosos: confirmación obligatoria
        if base_cmd in self.DANGEROUS_COMMANDS:
            return {"safe": True, "needs_confirmation": True,
                    "reason": f"'{base_cmd}' puede alterar el sistema"}

        # Subcomandos de solo lectura (ufw status, systemctl is-active...)
        if base_cmd in self.READONLY_SUBCOMMANDS:
            rest = " ".join(parts[1:]).strip().lower()
            if any(rest == ok or rest.startswith(ok + " ")
                   for ok in self.READONLY_SUBCOMMANDS[base_cmd]):
                return {"safe": True, "reason": ""}
            return {"safe": True, "needs_confirmation": True,
                    "reason": f"'{base_cmd}' solo lectura directa"}

        # Whitelist segura: pasa directo
        if base_cmd in self.SAFE_WHITELIST:
            return {"safe": True, "reason": ""}

        # Desconocido pero no obviamente malo: confirmación
        return {"safe": True, "needs_confirmation": True,
                "reason": f"comando '{base_cmd}' no verificado"}
        
    async def _run_command(self, command: str) -> Dict[str, Any]:
        """
        Execute a terminal command
        
        Args:
            command: Command to execute
            
        Returns:
            Dict with success, output, and error
        """
        from utils.safe_subprocess import run_shell
        rc, output, error = await run_shell(command, timeout=10.0,
                                            max_output=4000)
        output, error = output.strip(), error.strip()
        if rc == 124:
            return {'success': False, 'output': '',
                    'error': 'Comando excedió el tiempo límite'}
        return {
            'success': rc == 0,
            'output': output,
            'error': error if error else f"Código de salida: {rc}"
        }
