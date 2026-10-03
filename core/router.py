#!/usr/bin/env python3
"""
Router for Jarvis - Routes commands to appropriate skills.

Orden:
1. Reglas deterministas (regex / wildcard / keywords) con puntuación.
2. Si el mejor match es débil o nulo -> Brain (heurística + Groq/Ollama).
"""

import logging
import re
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class Router:
    """Routes commands to appropriate skills."""

    def __init__(self, skill_manager, brain, config=None):
        self.skill_manager = skill_manager
        self.brain = brain
        self.config = config

    async def route(self, text: str) -> Optional[str]:
        text_clean = text.strip()
        text_lower = text_clean.lower()

        best_skill = None
        best_skill_name = ""
        best_score = 0.0

        for skill_name, skill in self.skill_manager.skills.items():
            for pattern in getattr(skill, "patterns", []):
                score = self._score_pattern(text_lower, str(pattern))
                if score > best_score:
                    best_score = score
                    best_skill = skill
                    best_skill_name = skill_name

        # Umbral: 1.0 = match fuerte determinista
        if best_skill is not None and best_score >= 1.0:
            logger.info("Match determinista: %s (score %.2f)", best_skill_name, best_score)
            try:
                result = await best_skill.execute(text_clean)
            except Exception as e:
                logger.exception("Skill %s falló: %s", best_skill_name, e)
                return "Error al ejecutar la acción."
            if not isinstance(result, dict):
                return ""
            if result.get("silent", False):
                return ""
            return str(result.get("response", ""))

        logger.debug("Sin match fuerte (mejor %.2f). Uso Brain.", best_score)
        return await self._route_with_llm(text_clean)

    def _score_pattern(self, text: str, pattern: str) -> float:
        """0.0 = nada, 1.0 = fuerte, 0.5 = parcial."""
        p = pattern.strip().lower()
        if not p:
            return 0.0
        # Regex /.../ 
        if len(p) > 2 and p.startswith("/") and p.endswith("/"):
            try:
                if re.search(p[1:-1], text, re.IGNORECASE):
                    return 1.0
            except re.error:
                return 0.0
            return 0.0
        # Wildcard con *
        if "*" in p:
            regex = re.escape(p).replace(r"\*", ".*")
            try:
                if re.fullmatch(regex, text, re.IGNORECASE):
                    return 1.0
                if re.search(regex.strip(".*"), text, re.IGNORECASE):
                    return 0.5
            except re.error:
                return 0.0
            return 0.0
        # Frase exacta contenida -> fuerte
        if " " in p:
            return 1.0 if p in text else 0.0
        # Keyword suelto: fuerte solo si aparece como palabra completa
        if re.search(r"\b" + re.escape(p) + r"\b", text):
            return 1.0
        return 0.0

    def _matches_pattern(self, text: str, pattern: str) -> bool:
        """Compatibilidad: True si el score es fuerte."""
        return self._score_pattern(text.lower(), pattern) >= 1.0

    async def _route_with_llm(self, text: str) -> Optional[str]:
        try:
            intent = await self.brain.classify_intent(text)
        except Exception as e:
            logger.error("classify_intent falló: %s", e)
            intent = None

        if intent is None:
            try:
                return await self.brain.process_with_llm(text)
            except Exception:
                return "No entiendo esa instrucción."

        # Brain devuelve dataclass Intent o dict
        if hasattr(intent, "intent"):
            intent_name = getattr(intent, "intent")
            params = getattr(intent, "parameters", {}) or {}
        elif isinstance(intent, dict):
            intent_name = intent.get("intent", "")
            params = intent.get("parameters", {}) or {}
        else:
            return "No entiendo esa instrucción."

        if not intent_name or intent_name == "unknown":
            # Último recurso: respuesta breve del LLM
            try:
                return await self.brain.process_with_llm(text)
            except Exception:
                return "No entiendo esa instrucción."

        skill = self.skill_manager.get_skill_by_intent(intent_name)
        if skill is None:
            # Mapeo flexible: system.* -> skill 'system', etc.
            short = intent_name.split(".")[0]
            skill = self.skill_manager.get_skill(short)
        if skill is None:
            try:
                return await self.brain.process_with_llm(text)
            except Exception:
                return "No tengo habilidad para eso."

        try:
            result = await skill.execute(text, {"intent": intent_name, **params})
        except Exception as e:
            logger.exception("Skill vía LLM falló: %s", e)
            return "Error al ejecutar la acción."
        if not isinstance(result, dict):
            return ""
        if result.get("silent", False):
            return ""
        return str(result.get("response", ""))
