#!/usr/bin/env python3
"""
Ayuda de programación (asistida, nunca autónoma ciega).

- "abre vscode" / "abre cursor" / "abre este repo en vscode" -> editor en git root
- "abre la terminal en vscode" / "ejecuta los tests" / "npm test" ->
  comando dev de whitelist (timeout, salida truncada, audit)
- "arregla este error" / "revisa el repo" ->
  editor + OpenCode + prompt breve en clipboard
- Destructivos (rm, push --force...) -> pending con confirma/cancela

Whitelist y editores en config.yaml -> coding.*.
"""

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.platform import IS_WINDOWS, PlatformOps
from skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_EDITORS = ["cursor", "code", "codium"]
DEFAULT_ALLOWED = [
    "pytest", "python -m unittest", "npm test", "npm run build",
    "cargo test", "go test", "git status", "git diff",
]
BLOCKED_HINTS = ("rm ", "rm -rf", "push --force", "push -f", "mkfs",
                 "dd if=", "dd of=", "> /dev/", ":(){", "drop database")


class CodingSkill(Skill):
    """Abre editor, corre tests/lints seguros e integra OpenCode."""

    patterns = [
        "abre vscode y ejecuta los tests", "abre el editor y ejecuta",
        "abre vscode", "abre cursor", "abre el editor", "abre este repo en vscode",
        "abre la terminal en vscode", "ejecuta los tests", "corre pytest",
        "corre los tests", "npm test", "arregla este error", "ayuda con el código",
        "ayuda con el codigo", "revisa el repo", "revisa este repo",
        "soluciona", "abre code",
    ]

    intent = "coding"

    # Inyectado en main.py (y gui_server.py)
    config = None

    # -- config ------------------------------------------------------------
    def _cfg(self, key: str, default):
        try:
            return (self.config.get(f"coding.{key}", default)
                    if self.config else default)
        except Exception:
            return default

    def _editors(self) -> List[str]:
        faced = [e for e in self._cfg("editors", DEFAULT_EDITORS)]
        if IS_WINDOWS and not any(e.lower().endswith(".exe") for e in faced):
            faced = [f"{e}.exe" if e.lower() in ("code", "cursor") else e
                     for e in faced]
        return faced

    # -- repo / editor ------------------------------------------------------
    @staticmethod
    def git_root(start: Optional[Path] = None) -> Optional[Path]:
        current = (start or Path.cwd()).resolve()
        for parent in [current, *current.parents]:
            if (parent / ".git").exists():
                return parent
        return None

    def find_editor(self) -> Optional[str]:
        for editor in self._editors():
            if shutil.which(editor):
                return editor
        return None

    async def _open_editor(self, path: Optional[Path] = None) -> Dict[str, Any]:
        editor = self.find_editor()
        if editor is None:
            return {"response": "No encontré VS Code ni Cursor instalados.",
                    "silent": False}
        target = str(path or self.git_root() or Path.cwd())
        try:
            proc = await asyncio.create_subprocess_exec(
                editor, target,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await asyncio.sleep(0.3)
            if proc.returncode not in (None, 0):
                return {"response": f"{editor} falló al abrir.",
                        "silent": False}
            return {"response": "", "silent": True,
                    "audit_action": f"coding:open {Path(target).name}"}
        except FileNotFoundError:
            return {"response": f"No encontré {editor}.", "silent": False}
        except Exception as e:
            logger.error("Abrir editor falló: %s", e)
            return {"response": "No pude abrir el editor.", "silent": False}

    # -- comandos dev ---------------------------------------------------------
    def _allowed(self, command: str) -> bool:
        low = command.strip().lower()
        return any(low == a or low.startswith(a + " ") or low.startswith(a + ";")
                   for a in [a.lower() for a in self._cfg("allowed_commands",
                                                          DEFAULT_ALLOWED)])

    @staticmethod
    def _destructive(command: str) -> bool:
        low = command.lower()
        return any(h in low for h in BLOCKED_HINTS)

    async def _run_dev(self, command: str, cwd: Optional[Path] = None) -> Dict[str, Any]:
        from utils.safe_subprocess import run_shell
        rc, text, _ = await run_shell(
            command, timeout=120.0, max_output=800,
            cwd=str(cwd or self.git_root() or Path.cwd()))
        if rc == 124:
            return {"response": f"{command}: excedió 2 minutos.", "silent": False}
        status = "OK" if rc == 0 else f"falló ({rc})"
        return {"response": f"{command}: {status}. {text.strip()}".strip(),
                "silent": False,
                "audit_action": f"coding:run {command[:60]}"}

    def _extract_command(self, text: str) -> str:
        cleaned = re.sub(r"^(ejecuta|corre|corre los|ejecuta los)\s+", "",
                         text.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"^tests\s*", "pytest" if not IS_WINDOWS else "pytest",
                         cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    # -- execute -----------------------------------------------------------------
    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        low = text.lower()

        # Compuesto: editor + tests ("abre vscode y ejecuta los tests")
        if ("vscode" in low or "cursor" in low or "editor" in low) and \
                ("test" in low or "pytest" in low or "unittest" in low):
            opened = await self._open_editor()
            if opened.get("silent") is not True:
                return opened
            ran = await self._run_dev("pytest" if "pytest" in low or "test" in low
                                      else "python -m unittest")
            resp = ran.get("response", "")
            return {"response": f"Editor abierto. {resp}", "silent": False,
                    "audit_action": "coding:open+test"}

        # Abrir editor / repo
        if any(w in low for w in ("vscode", "cursor", "editor", "code")) \
                and "test" not in low and "unittest" not in low \
                and "pytest" not in low and "npm" not in low:
            return await self._open_editor()

        # Pedir arreglo/revisión -> editor + OpenCode + prompt en clipboard
        if any(w in low for w in ("arregla", "ayuda con", "revisa", "soluciona")):
            return await self._assist_fix(text)

        # Comando dev explícito
        command = self._extract_command(text)
        if self._destructive(command):
            async def _run_confirmed():
                return await self._run_dev(command)
            return {"response": f"Comando delicado: {command}. Di confirma o cancela.",
                    "silent": False, "requires_confirmation": True,
                    "deferred_execute": _run_confirmed,
                    "audit_action": f"coding:run {command[:60]}"}
        if self._allowed(command):
            return await self._run_dev(command)
        return {"response": f"Comando no permitido: {command}.",
                "silent": False}

    async def _assist_fix(self, text: str) -> Dict[str, Any]:
        """Abre editor + lanza OpenCode + deja prompt en clipboard."""
        repo = self.git_root() or Path.cwd()
        opened = await self._open_editor(repo)
        launched = ""
        try:
            from skills.opencode import OpencodeSkill
            res = await OpencodeSkill().execute("revisa este repo")
            if res.get("silent"):
                launched = " OpenCode lanzado."
        except Exception as e:
            logger.debug("OpenCode bridge falló: %s", e)
        prompt = f"Ayúdame con esto en {repo.name}: {text.strip()[:200]}"
        clip = await PlatformOps.copy_to_clipboard(prompt)
        parts = []
        if opened.get("silent"):
            parts.append(f"Abrí {repo.name} en el editor")
        else:
            parts.append(opened.get("response", ""))
        parts.append(launched.strip() or "OpenCode no disponible")
        parts.append("prompt en clipboard." if clip else "sin clipboard")
        if self._cfg("open_opencode_on_fix_requests", True) is False:
            parts = [p for p in parts if "OpenCode" not in p]
        return {"response": " ".join(p for p in parts if p).strip() + ".",
                "silent": False, "audit_action": "coding:assist-fix"}
