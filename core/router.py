#!/usr/bin/env python3
"""
Router for Jarvis - Routes commands to appropriate skills.

Orden:
0. Pedidos ofensivos -> rechazo directo (nunca atacar terceros).
1. Si hay acción pendiente -> confirma/cancela por voz (antes que todo).
2. Reglas deterministas (regex / wildcard / keywords) con puntuación.
3. Si el mejor match es débil o nulo -> Brain (heurística + Groq/Ollama).
4. Cada ejecución de skill se registra en el audit (salvo ruido).
"""

import logging
import re
import time
from typing import Optional, Dict, Any

from core.audit import AuditEntry, AuditLog
from core.chat import ChatSession
from core.pending import PendingManager

logger = logging.getLogger(__name__)

# Skills que solo consultan: no ensucian el audit (salvo ruido).
_NO_AUDIT_INTENTS = {"audit"}


class Router:
    """Routes commands to appropriate skills."""

    def __init__(self, skill_manager, brain, config=None,
                 pending: Optional[PendingManager] = None,
                 audit: Optional[AuditLog] = None,
                 chat_session: Optional[ChatSession] = None):
        self.skill_manager = skill_manager
        self.brain = brain
        self.config = config
        timeout = 12.0
        try:
            if config is not None:
                timeout = float(config.get("pending.timeout_seconds", 12.0))
        except Exception:
            pass
        self.pending = pending or PendingManager(timeout_seconds=timeout)
        self.chat_session = chat_session or ChatSession()
        self.audit = audit or AuditLog(
            enabled=bool(config.get("audit.enabled", True)) if config else True)
        # Patterns precompilados por skill (se compilan una vez, no por frase)
        self._compiled: Dict[str, list] = {}
        self._compiled_keys: tuple = ()

    @staticmethod
    def _is_chat_command(text_lower: str) -> bool:
        """Órdenes del propio modo chat (entrar/salir) van a la skill."""
        from skills.chat import ChatSkill
        return any(p in text_lower for p in ChatSkill.patterns)

    async def _chat_reply(self, text_clean: str) -> str:
        session = self.chat_session
        session.add("user", text_clean)
        try:
            response = await self.brain.chat_reply(session.history)
        except Exception as e:
            logger.error("Chat falló: %s", e)
            response = "No pude responder ahora."
        session.add("assistant", response)
        return response

    def _timings_on(self) -> bool:
        try:
            return bool((self.config.get("performance", {}) or {}).get(
                "log_timings", False)) if self.config else False
        except Exception:
            return False

    async def route(self, text: str) -> Optional[str]:
        import time
        t0 = time.perf_counter()
        text_clean = text.strip()
        text_lower = text_clean.lower()

        # 0) Rechazo ofensivo: nunca atacar otros sistemas (antes que todo)
        try:
            from skills.security import REFUSAL, is_offensive_request
            if is_offensive_request(text_clean):
                logger.info("Pedido ofensivo rechazado.")
                return REFUSAL
        except ImportError:
            pass

        # 1) Pending primero: confirma/cancela/recuerda
        reply = await self.pending.handle_reply(text_clean)
        if reply is not None:
            return reply

        # 1b) Modo chat: todo va al LLM salvo órdenes del propio chat
        if self.chat_session.active and not self._is_chat_command(text_lower):
            return await self._chat_reply(text_clean)

        from core.nlu import FUZZY_THRESHOLD, canonicalize, fuzzy_match
        canon = canonicalize(text_clean)

        best_skill = None
        best_skill_name = ""
        best_score = 0.0
        best_len = -1

        for skill_name, compiled in self._compiled_patterns().items():
            skill = self.skill_manager.skills[skill_name]
            for kind, payload, plen, pcanon in compiled:
                score = self._score_compiled(text_lower, kind, payload)
                # Capa difusa: tildes, typos y STT ruidoso ("bajale el bolumen")
                if score < 1.0 and pcanon:
                    if fuzzy_match(canon, pcanon) >= FUZZY_THRESHOLD:
                        score = 1.0
                # Desempate: a igual score gana el patrón más específico
                # ("abre vscode y ejecuta los tests" -> coding, no apps).
                if (score > best_score
                        or (score == best_score and score >= 1.0
                            and plen > best_len)):
                    best_score = score
                    best_len = plen
                    best_skill = skill
                    best_skill_name = skill_name

        # 2) Match fuerte determinista
        if best_skill is not None and best_score >= 1.0:
            logger.info("Match determinista: %s (score %.2f)", best_skill_name, best_score)
            import time as _t
            t_skill = _t.perf_counter()
            try:
                result = await best_skill.execute(text_clean)
            except Exception as e:
                logger.exception("Skill %s falló: %s", best_skill_name, e)
                return "Error al ejecutar la acción."
            out = await self._finish(text_clean, best_skill_name, best_skill, result)
            if self._timings_on():
                import time as _t2
                logger.info("timings route=%.1fms skill=%s:%.1fms",
                            (_t2.perf_counter() - t0) * 1000,
                            best_skill_name,
                            (_t2.perf_counter() - t_skill) * 1000)
            return out

        logger.debug("Sin match fuerte (mejor %.2f). Uso Brain.", best_score)
        return await self._route_with_llm(text_clean)

    async def _finish(self, text_clean: str, skill_name: str,
                      skill, result: Any) -> str:
        """Procesa el dict de una skill: pending, audit y respuesta."""
        if not isinstance(result, dict):
            return ""
        # Confirmación en 2 turnos: "confirma" ya venía en la frase -> directo
        if result.get("requires_confirmation") and result.get("deferred_execute"):
            low = text_clean.lower()
            if "confirma" in low or "confirmo" in low:
                try:
                    confirmed = await result["deferred_execute"]()
                except Exception as e:
                    logger.exception("Deferred falló: %s", e)
                    return "Error al ejecutar la acción confirmada."
                return await self._finish(text_clean, skill_name, skill, confirmed)
            deferred = result["deferred_execute"]

            async def _audited():
                out = await deferred()
                if isinstance(out, dict):
                    self._write_audit(text_clean, skill_name, skill, out)
                return out

            await self.pending.set(
                description=self._describe(skill_name, result),
                deferred=_audited)
            return str(result.get("response", "Di confirma o cancela."))
        # Compat: skills que piden confirma sin deferred (terminal)
        if result.get("requires_confirmation"):
            return str(result.get("response", ""))
        self._write_audit(text_clean, skill_name, skill, result)
        if result.get("silent", False):
            return ""
        return str(result.get("response", ""))

    @staticmethod
    def _describe(skill_name: str, result: Dict[str, Any]) -> str:
        action = result.get("audit_action") or skill_name
        return str(action).split("?")[0].replace("system:", "")

    def _write_audit(self, text_clean: str, skill_name: str,
                     skill, result: Dict[str, Any]) -> None:
        if result.get("no_audit"):
            return
        intent = getattr(skill, "intent", "") or skill_name
        if intent in _NO_AUDIT_INTENTS or skill_name in _NO_AUDIT_INTENTS:
            return
        if self.audit is None:
            return
        action = str(result.get("audit_action") or intent)
        self.audit.log(AuditEntry(
            ts=time.time(), skill=skill_name, text=text_clean,
            action=action, result=str(result.get("response", ""))[:200],
            reversible=bool(result.get("reversible", False)),
            undo_payload=dict(result.get("undo_payload", {}) or {})))

    def _compiled_patterns(self) -> Dict[str, list]:
        """Compila una vez los patterns de cada skill (regex cacheadas)."""
        keys = tuple(sorted(self.skill_manager.skills.keys()))
        if keys != self._compiled_keys:
            compiled: Dict[str, list] = {}
            for name, skill in self.skill_manager.skills.items():
                items = []
                for pattern in getattr(skill, "patterns", []):
                    p = str(pattern).strip().lower()
                    if not p:
                        continue
                    try:
                        from core.nlu import canonicalize as _canon
                        pcanon = _canon(p)
                    except Exception:
                        pcanon = p
                    if len(p) > 2 and p.startswith("/") and p.endswith("/"):
                        try:
                            items.append(("regex", re.compile(p[1:-1]), len(p), pcanon))
                        except re.error:
                            continue
                    elif "*" in p:
                        try:
                            rx = re.compile(re.escape(p).replace(r"\*", ".*"))
                            inner = re.compile(rx.pattern.strip(".*")) \
                                if rx.pattern.strip(".*") else None
                            items.append(("wild", (rx, inner), len(p), pcanon))
                        except re.error:
                            continue
                    elif " " in p:
                        items.append(("phrase", p, len(p), pcanon))
                    else:
                        try:
                            items.append(("word", re.compile(
                                r"\b" + re.escape(p) + r"\b"), len(p), pcanon))
                        except re.error:
                            continue
                compiled[name] = items
            self._compiled = compiled
            self._compiled_keys = keys
        return self._compiled

    def _score_compiled(self, text: str, kind: str, payload) -> float:
        """0.0 = nada, 1.0 = fuerte, 0.5 = parcial (sin recompilar)."""
        if kind == "regex":
            return 1.0 if payload.search(text) else 0.0
        if kind == "wild":
            rx, inner = payload
            if rx.fullmatch(text):
                return 1.0
            if inner is not None and inner.search(text):
                return 0.5
            return 0.0
        if kind == "phrase":
            return 1.0 if payload in text else 0.0
        # kind == "word"
        return 1.0 if payload.search(text) else 0.0

    def _score_pattern(self, text: str, pattern: str) -> float:
        """Compatibilidad (tests): compila al vuelo un solo patrón."""
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
        # 3a) Tool-calling: el LLM elige skill + parámetros (Groq real)
        try:
            tool = await self.brain.process_with_tools(text)
        except Exception as e:
            logger.error("process_with_tools falló: %s", e)
            tool = None
        if tool:
            skill_name, args, template = tool
            skill = self.skill_manager.get_skill(skill_name)
            if skill is not None:
                try:
                    canon = template.format(**{k: args.get(k, "") for k in
                        ("direction", "percent", "action", "app", "command",
                         "query", "minutes", "message", "what")})
                except (KeyError, IndexError, ValueError):
                    canon = text
                logger.info("Tool-call: %s -> skill %s", skill_name, canon)
                try:
                    result = await skill.execute(canon.strip() or text,
                                                 {"intent": skill_name,
                                                  **args})
                except Exception as e:
                    logger.exception("Skill vía tools falló: %s", e)
                    return "Error al ejecutar la acción."
                return await self._finish(canon, skill_name, skill, result)

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
            confidence = float(getattr(intent, "confidence", 0.0) or 0.0)
        elif isinstance(intent, dict):
            intent_name = intent.get("intent", "")
            params = intent.get("parameters", {}) or {}
            confidence = float(intent.get("confidence", 0.0) or 0.0)
        else:
            return "No entiendo esa instrucción."

        if not intent_name or intent_name == "unknown":
            # Último recurso: respuesta breve del LLM
            try:
                return await self.brain.process_with_llm(text)
            except Exception:
                return "No entiendo esa instrucción."

        # Baja confianza + intención sensible: no ejecutar automáticamente.
        risky_prefixes = ("system.", "terminal.", "security.")
        min_conf = 0.68
        try:
            min_conf = float(self.config.get("router.min_llm_confidence", 0.68))
        except Exception:
            pass
        if confidence < min_conf and intent_name.startswith(risky_prefixes):
            logger.warning("Intento LLM inseguro: intent=%s conf=%.2f", intent_name, confidence)
            return "No tengo suficiente confianza para ejecutar eso. ¿Puedes reformularlo?"

        skill = self.skill_manager.get_skill_by_intent(intent_name)
        if skill is None:
            # Mapeo flexible: system.* -> skill 'system', etc.
            short = intent_name.split(".")[0]
            skill = self.skill_manager.get_skill(short)
        if skill is None:
            skill_name = intent_name.split(".")[0]
        else:
            skill_name = next(
                (n for n, s in self.skill_manager.skills.items() if s is skill),
                intent_name.split(".")[0])

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
        logger.info("LLM->skill: intent=%s conf=%.2f skill=%s",
                    intent_name, confidence, skill_name)
        return await self._finish(text, skill_name, skill, result)
