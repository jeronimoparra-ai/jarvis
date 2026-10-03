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

async def main():
    """Punto de entrada principal"""
    # Configurar logging centralizado
    logger = setup_logger("jarvis", "jarvis.log")
    logger.info("Iniciando Jarvis...")
    
    # Cargar configuración (ruta robusta junto a main.py) y .env
    base_dir = Path(__file__).resolve().parent
    config = Config(str(base_dir / "config.yaml"))
    
    # Inicializar componentes pasándoles la configuración
    skill_manager = SkillManager(config)
    brain = Brain(config)
    audio = AudioSystem(skill_manager, brain, config)
    router = Router(skill_manager, brain, config)
    
    # Asociar enrutador a audio para su procesamiento
    audio.router = router
    
    # Cargar skills
    await skill_manager.load_skills()
    
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
