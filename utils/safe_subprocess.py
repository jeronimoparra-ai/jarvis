#!/usr/bin/env python3
"""
Subprocess seguro y único para todo Jarvis.

- Timeout obligatorio (default 10 s) con kill del hijo al expirar.
- Salida truncada (default 4000 chars) para no inundar logs/RAM.
- run_exec(): lista de args, SIN shell (preferido).
- run_shell(): solo para comandos internos ya validados; nunca con
  entrada cruda del usuario sin pasar por la whitelist de terminal.
"""

import asyncio
import logging
from typing import List, Optional, Sequence, Union

logger = logging.getLogger(__name__)


async def _drain(proc: "asyncio.subprocess.Process",
                 timeout: float, max_output: int) -> tuple[int, str, str]:
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        except Exception:
            out, err = b"", b"TIMEOUT"
        return 124, _cut(out, max_output), "TIMEOUT"
    return (proc.returncode or 0,
            _cut(out, max_output), _cut(err, max_output))


def _cut(data: Union[bytes, str, None], max_output: int) -> str:
    if not data:
        return ""
    text = data.decode(errors="replace") if isinstance(data, bytes) else data
    if len(text) > max_output:
        return text[:max_output] + "…[truncado]"
    return text


async def run_exec(args: Sequence[str], timeout: float = 10.0,
                   max_output: int = 4000) -> tuple[int, str, str]:
    """Ejecuta argv sin shell. Devuelve (rc, stdout, stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError:
        return 127, "", f"no encontrado: {args[0] if args else '?'}"
    except Exception as e:
        logger.debug("run_exec falló: %s", e)
        return 1, "", str(e)[:200]
    return await _drain(proc, timeout, max_output)


async def run_shell(cmd: str, timeout: float = 10.0,
                    max_output: int = 4000,
                    cwd: Optional[str] = None) -> tuple[int, str, str]:
    """Ejecuta vía shell (solo comandos internos validados)."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=cwd)
    except Exception as e:
        logger.debug("run_shell falló: %s", e)
        return 1, "", str(e)[:200]
    return await _drain(proc, timeout, max_output)
