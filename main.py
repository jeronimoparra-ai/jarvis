#!/usr/bin/env python3
"""
Jarvis - Sistema de asistente de voz tipo Jarvis para Linux
Task-oriented voice assistant with modular skills system
"""

import asyncio
import logging
import sys
from pathlib import Path

from utils.config import Config
from utils.logger import setup_logger
from core.audio import AudioSystem
from core.router import Router
from core.brain import Brain
from core.skill_manager import SkillManager
from core.pending import PendingManager
from core.audit import AuditLog
from core.profiles import apply_profile_to_config

async def main():
    """Punto de entrada principal"""
    from utils.banner import print_banner
    print_banner()
    # Configurar logging centralizado
    logger = setup_logger("jarvis", "jarvis.log")
    logger.info("Iniciando Jarvis...")

    # Cargar configuración (ruta robusta junto a main.py) y .env
    base_dir = Path(__file__).resolve().parent
    config = Config(str(base_dir / "config.yaml"))

    # Perfil de máquina (laptop/desktop) como overlay
    profile = apply_profile_to_config(config, base_dir)
    from core.platform import SYSTEM, IS_WINDOWS
    logger.info("SO detectado: %s | Perfil activo: %s", SYSTEM, profile)
    if IS_WINDOWS:
        logger.info("Modo Windows: volumen/ventanas/portapapeles en best-effort.")

    # Núcleo: pending por voz + audit log
    pending = PendingManager(
        timeout_seconds=float(config.get("pending.timeout_seconds", 12)))
    audit = AuditLog(enabled=bool(config.get("audit.enabled", True)))

    # Inicializar componentes pasándoles la configuración
    skill_manager = SkillManager(config)
    brain = Brain(config)
    audio = AudioSystem(skill_manager, brain, config)
    router = Router(skill_manager, brain, config, pending=pending, audit=audit)

    # Asociar enrutador a audio para su procesamiento
    audio.router = router

    # Cargar skills
    await skill_manager.load_skills()
    logger.info("Skills cargadas: %s", sorted(skill_manager.list_skills()))

    # Inyectar dependencias en skills que las necesitan
    from skills.audit_skill import AuditSkill
    AuditSkill.audit = audit
    from skills.system import register_system_undo_handlers
    await register_system_undo_handlers(audit)
    try:
        from skills.routines import RoutinesSkill
        RoutinesSkill.manager = skill_manager
        RoutinesSkill.config = config
    except ImportError:
        pass
    try:
        from skills.media import MediaSkill
        MediaSkill.config = config
    except ImportError:
        pass
    try:
        from skills.coding import CodingSkill
        CodingSkill.config = config
    except ImportError:
        pass
    try:
        from skills.security import SecuritySkill
        SecuritySkill.config = config
    except ImportError:
        pass
    try:
        from skills.chat import ChatSkill
        ChatSkill.session = router.chat_session
    except ImportError:
        pass
    try:
        from skills.status import StatusSkill
        StatusSkill.config = config
    except ImportError:
        pass
    try:
        from skills.reminder import ReminderSkill
        reminder = skill_manager.get_skill("reminder")
        if reminder is not None and hasattr(reminder, "set_announce_callback"):
            async def _announce(message: str) -> None:
                await audio.speak(f"Recordatorio: {message}")
            reminder.set_announce_callback(_announce)
    except ImportError:
        pass

    # Iniciar sistema
    try:
        success = await audio.initialize()
        if not success:
            logger.warning("El sistema de audio no pudo inicializarse por completo. Ejecutando en modo simulación (teclado).")

        await brain.initialize()
        logger.info("Cerebro de Jarvis (LLM) inicializado")

        logger.info("Asistente listo y escuchando wake word...")
        await audio.listen_for_wake_word()
    except KeyboardInterrupt:
        logger.info("Cerrando Jarvis por interrupción de teclado...")
    except Exception as e:
        logger.exception(f"Error fatal durante la ejecución: {e}")
    finally:
        await audio.cleanup()
        await brain.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
