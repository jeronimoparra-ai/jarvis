#!/usr/bin/env python3
"""
Brain for Jarvis - LLM processing and intent classification.

Remote-first multi-provider strategy:
- Groq
- Cerebras
- Gemini
- OpenRouter
- Offline mock fallback
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

import aiohttp

from utils.config import Config

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    GROQ = "groq"
    CEREBRAS = "cerebras"
    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"  # compat legado
    OFFLINE = "offline"
    MOCK = "offline"    # alias compat tests previos


@dataclass
class Intent:
    """Classified intent result."""
    intent: str
    confidence: float
    parameters: Dict[str, Any]


class LLMCallError(Exception):
    def __init__(self, message: str, *, retryable: bool = True,
                 status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


def _extract_json_object(raw: str) -> dict:
    """Parse JSON robusto. Si viene con texto extra, intenta extraer objeto."""
    if not raw:
        return {}
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return {}


class BaseLLMProvider:
    name: str = "base"

    def __init__(self, model: str, timeout_s: float = 10.0):
        self.model = model
        self.timeout_s = timeout_s

    def available(self) -> bool:
        raise NotImplementedError

    async def generate(self, prompt: str, max_tokens: int,
                       temperature: float) -> str:
        raise NotImplementedError

    async def classify_intent(self, text: str) -> dict:
        raise NotImplementedError

    async def chat(self, messages: list[dict], max_tokens: int,
                   temperature: float) -> str:
        raise NotImplementedError

    async def tool_call(self, text: str, tools: list, tool_specs: list) -> Optional[tuple[str, dict, str]]:
        return None

    async def health_check(self) -> bool:
        return self.available()

    def model_name(self) -> str:
        return self.model

    async def close(self) -> None:
        return


class GroqProvider(BaseLLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, timeout_s: float = 10.0):
        super().__init__(model=model, timeout_s=timeout_s)
        self.api_key = api_key
        self.client = None
        if api_key:
            try:
                from groq import AsyncGroq
                self.client = AsyncGroq(api_key=api_key, timeout=timeout_s)
            except Exception as e:  # pragma: no cover - depende del entorno
                logger.warning("Groq no disponible: %s", e)

    def available(self) -> bool:
        return bool(self.client and self.api_key)

    async def generate(self, prompt: str, max_tokens: int,
                       temperature: float) -> str:
        if not self.client:
            raise LLMCallError("Groq no inicializado", retryable=False)
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            raise LLMCallError(str(e), retryable=True) from e

    async def classify_intent(self, text: str) -> dict:
        if not self.client:
            raise LLMCallError("Groq no inicializado", retryable=False)
        prompt = (
            "Clasifica la intención del comando en español y responde SOLO JSON.\n"
            "Formato: {\"intent\":\"...\",\"confidence\":0.0,\"parameters\":{}}\n"
            "Intentos válidos: "
            "system.restart|system.shutdown|system.volume|apps.open|apps.close|"
            "web.search|terminal.execute|clock.time|media.control|reminder.create|"
            "window.close|window.which|window.capture|routines.run|dictation.write|"
            "status.report|audit.query|security.check|coding.help|unknown\n"
            f"Comando: {text}"
        )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw = (response.choices[0].message.content or "").strip()
            return _extract_json_object(raw)
        except Exception as e:
            raise LLMCallError(str(e), retryable=True) from e

    async def chat(self, messages: list[dict], max_tokens: int,
                   temperature: float) -> str:
        if not self.client:
            raise LLMCallError("Groq no inicializado", retryable=False)
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            raise LLMCallError(str(e), retryable=True) from e

    async def tool_call(self, text: str, tools: list,
                        tool_specs: list) -> Optional[tuple[str, dict, str]]:
        if not self.client:
            return None
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "Eres el router de Jarvis. Elige UNA herramienta o ninguna. "
                        "No propongas comandos destructivos.")},
                    {"role": "user", "content": text},
                ],
                tools=tools,
                tool_choice="auto",
                max_tokens=120,
                temperature=0.0,
            )
            calls = response.choices[0].message.tool_calls
            if not calls:
                return None
            call = calls[0]
            for tool in tool_specs:
                fn = tool["function"]
                if fn["name"] == call.function.name:
                    args = _extract_json_object(call.function.arguments or "{}")
                    return fn.get("skill", ""), args, fn.get("synthesize", "")
            return None
        except Exception as e:
            raise LLMCallError(str(e), retryable=True) from e

    async def close(self) -> None:
        if self.client is not None and hasattr(self.client, "close"):
            await self.client.close()


class OpenAICompatProvider(BaseLLMProvider):
    def __init__(self, name: str, api_key: str, base_url: str,
                 model: str, timeout_s: float = 10.0):
        super().__init__(model=model, timeout_s=timeout_s)
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout_s)
        )

    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }
        if self.name == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/jeronimoparra-ai/jarvis"
            headers["X-Title"] = "Jarvis"
        return headers

    async def _chat_completion(self, payload: dict) -> dict:
        if not self.available():
            raise LLMCallError(f"{self.name} sin API key", retryable=False)
        url = f"{self.base_url}/chat/completions"
        try:
            async with self.session.post(url, headers=self._headers(), json=payload) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    retryable = resp.status in {408, 409, 425, 429, 500, 502, 503, 504}
                    raise LLMCallError(
                        f"{self.name} HTTP {resp.status}: {text[:180]}",
                        retryable=retryable,
                        status=resp.status,
                    )
                return _extract_json_object(text)
        except asyncio.TimeoutError as e:
            raise LLMCallError(f"{self.name} timeout", retryable=True) from e
        except aiohttp.ClientError as e:
            raise LLMCallError(f"{self.name} error de red: {e}", retryable=True) from e

    async def generate(self, prompt: str, max_tokens: int,
                       temperature: float) -> str:
        data = await self._chat_completion({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        return ((data.get("choices") or [{}])[0].get("message", {})
                .get("content", "").strip())

    async def classify_intent(self, text: str) -> dict:
        prompt = (
            "Devuelve SOLO JSON con intent, confidence y parameters para este comando: "
            f"{text}"
        )
        data = await self._chat_completion({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 120,
            "temperature": 0.0,
        })
        content = ((data.get("choices") or [{}])[0].get("message", {})
                   .get("content", ""))
        return _extract_json_object(content)

    async def chat(self, messages: list[dict], max_tokens: int,
                   temperature: float) -> str:
        data = await self._chat_completion({
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        return ((data.get("choices") or [{}])[0].get("message", {})
                .get("content", "").strip())

    async def tool_call(self, text: str, tools: list,
                        tool_specs: list) -> Optional[tuple[str, dict, str]]:
        data = await self._chat_completion({
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Elige una herramienta o ninguna."},
                {"role": "user", "content": text},
            ],
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": 120,
            "temperature": 0.0,
        })
        tool_calls = ((data.get("choices") or [{}])[0].get("message", {})
                      .get("tool_calls") or [])
        if not tool_calls:
            return None
        call = tool_calls[0]
        fn_name = (((call.get("function") or {}).get("name")) or "").strip()
        fn_args = _extract_json_object(((call.get("function") or {}).get("arguments") or "{}"))
        for tool in tool_specs:
            fn = tool["function"]
            if fn["name"] == fn_name:
                return fn.get("skill", ""), fn_args, fn.get("synthesize", "")
        return None

    async def close(self) -> None:
        await self.session.close()


class GeminiProvider(BaseLLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_s: float = 10.0):
        super().__init__(model=model, timeout_s=timeout_s)
        self.api_key = api_key
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout_s)
        )

    def available(self) -> bool:
        return bool(self.api_key)

    async def _generate_content(self, prompt: str,
                                temperature: float = 0.1) -> str:
        if not self.available():
            raise LLMCallError("Gemini sin API key", retryable=False)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature},
        }
        try:
            async with self.session.post(url, json=payload) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    retryable = resp.status in {408, 409, 425, 429, 500, 502, 503, 504}
                    raise LLMCallError(
                        f"Gemini HTTP {resp.status}: {text[:180]}",
                        retryable=retryable,
                        status=resp.status,
                    )
                data = _extract_json_object(text)
                parts = (((data.get("candidates") or [{}])[0].get("content") or {})
                         .get("parts") or [{}])
                return str(parts[0].get("text", "")).strip()
        except asyncio.TimeoutError as e:
            raise LLMCallError("Gemini timeout", retryable=True) from e
        except aiohttp.ClientError as e:
            raise LLMCallError(f"Gemini red: {e}", retryable=True) from e

    async def generate(self, prompt: str, max_tokens: int,
                       temperature: float) -> str:
        _ = max_tokens  # la API no usa max_tokens igual que OpenAI
        return await self._generate_content(prompt, temperature)

    async def classify_intent(self, text: str) -> dict:
        prompt = (
            "Responde SOLO JSON con intent, confidence y parameters para: "
            f"{text}"
        )
        return _extract_json_object(await self._generate_content(prompt, 0.0))

    async def chat(self, messages: list[dict], max_tokens: int,
                   temperature: float) -> str:
        _ = max_tokens
        compact = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in messages[-10:])
        return await self._generate_content(compact, temperature)

    async def close(self) -> None:
        await self.session.close()


class OfflineProvider(BaseLLMProvider):
    name = "offline"

    def __init__(self):
        super().__init__(model="offline")

    def available(self) -> bool:
        return True

    async def generate(self, prompt: str, max_tokens: int,
                       temperature: float) -> str:
        _ = max_tokens, temperature
        low = prompt.lower()
        if "hola" in low:
            return "Hola, señor. Listo para recibir instrucciones."
        if "quién eres" in low or "quien eres" in low:
            return "Soy Jarvis, su asistente personal modular para Linux."
        return "Entendido."

    async def classify_intent(self, text: str) -> dict:
        _ = text
        return {}

    async def chat(self, messages: list[dict], max_tokens: int,
                   temperature: float) -> str:
        _ = max_tokens, temperature
        last = next((m.get("content", "") for m in reversed(messages)
                     if m.get("role") == "user"), "")
        return f"Te escucho: {last}".strip()


class LLMManager:
    def __init__(self, config: Config, tool_schemas: list, tool_specs: list):
        self.config = config
        self.tool_schemas = tool_schemas
        self.tool_specs = tool_specs
        self.providers: dict[str, BaseLLMProvider] = {}
        self.order: list[str] = []
        self.active: str = "offline"

        self.retry_attempts = max(1, int(config.get("llm.retry.max_attempts", 2)))
        self.backoff_s = float(config.get("llm.retry.base_backoff_s", 0.5))
        self.max_provider_attempts = max(1, int(config.get("llm.max_provider_attempts", 5)))

    @staticmethod
    def _api_key(config: Config, key_path: str, env_key: str) -> str:
        val = str(config.get(key_path, "") or "").strip()
        if val and not val.startswith("YOUR_"):
            return val
        env = str(os.getenv(env_key, "") or "").strip()
        if env and not env.startswith("YOUR_"):
            return env
        return ""

    @staticmethod
    def _dedupe_keep_order(items: list[str]) -> list[str]:
        seen = set()
        out: list[str] = []
        for item in items:
            k = (item or "").strip().lower()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(k)
        return out

    async def initialize(self) -> None:
        timeout_s = float(self.config.get("performance.http_timeout_s", 10))

        self.providers["groq"] = GroqProvider(
            api_key=self._api_key(self.config, "llm.groq.api_key", "GROQ_API_KEY"),
            model=str(self.config.get("llm.groq.model", "llama-3.1-8b-instant")),
            timeout_s=timeout_s,
        )
        self.providers["cerebras"] = OpenAICompatProvider(
            name="cerebras",
            api_key=self._api_key(self.config, "llm.cerebras.api_key", "CEREBRAS_API_KEY"),
            base_url=str(self.config.get("llm.cerebras.base_url", "https://api.cerebras.ai/v1")),
            model=str(self.config.get("llm.cerebras.model", "llama3.1-8b")),
            timeout_s=timeout_s,
        )
        self.providers["gemini"] = GeminiProvider(
            api_key=self._api_key(self.config, "llm.gemini.api_key", "GEMINI_API_KEY"),
            model=str(self.config.get("llm.gemini.model", "gemini-1.5-flash")),
            timeout_s=timeout_s,
        )
        self.providers["openrouter"] = OpenAICompatProvider(
            name="openrouter",
            api_key=self._api_key(self.config, "llm.openrouter.api_key", "OPENROUTER_API_KEY"),
            base_url=str(self.config.get("llm.openrouter.base_url", "https://openrouter.ai/api/v1")),
            model=str(self.config.get("llm.openrouter.model", "meta-llama/llama-3.1-8b-instruct:free")),
            timeout_s=timeout_s,
        )
        self.providers["offline"] = OfflineProvider()

        primary = str(self.config.get("llm.provider", "groq") or "groq").lower()
        fallback_order = self.config.get("llm.fallback_order", []) or []
        if not isinstance(fallback_order, list):
            fallback_order = []
        order = [primary, *[str(v) for v in fallback_order], "offline"]
        self.order = self._dedupe_keep_order(order)

        self.active = "offline"
        for name in self.order:
            provider = self.providers.get(name)
            if provider and provider.available():
                self.active = name
                break
        logger.info("LLM order: %s | activo: %s", self.order, self.active)

    def active_provider(self) -> BaseLLMProvider:
        return self.providers.get(self.active, self.providers["offline"])

    async def call(self, method: str, *args, **kwargs):
        attempts = 0
        for name in self.order:
            if attempts >= self.max_provider_attempts:
                break
            provider = self.providers.get(name)
            if provider is None or not provider.available():
                continue
            attempts += 1
            op = getattr(provider, method)
            for retry in range(self.retry_attempts):
                try:
                    result = await op(*args, **kwargs)
                    self.active = name
                    return result
                except LLMCallError as e:
                    if e.retryable and retry < self.retry_attempts - 1:
                        await asyncio.sleep(self.backoff_s * (2 ** retry))
                        continue
                    logger.warning("LLM %s %s falló: %s", name, method, e)
                    break
                except Exception as e:  # pragma: no cover - safety net
                    logger.warning("LLM %s %s excepción: %s", name, method, e)
                    break
        self.active = "offline"
        fallback = self.providers["offline"]
        return await getattr(fallback, method)(*args, **kwargs)

    async def close(self) -> None:
        for provider in self.providers.values():
            try:
                await provider.close()
            except Exception:
                continue


class Brain:
    """LLM brain for Jarvis - handles fallback reasoning."""

    _MOCK_CACHE_TTL = 60.0
    _MOCK_CACHE_MAX = 32

    def __init__(self, config: Config):
        self.config = config
        self.llm_provider: LLMProvider = LLMProvider.OFFLINE
        self.client = None  # compat con tests que mockean cliente Groq
        self.manager: Optional[LLMManager] = None
        self._mock_cache: Dict[str, tuple[float, str]] = {}

    TOOLS = [
        {"type": "function", "function": {
            "name": "system_volume",
            "description": "Subir, bajar o silenciar el volumen del equipo",
            "parameters": {"type": "object", "properties": {
                "direction": {"type": "string", "enum": ["sube", "baja", "silencia"]},
                "percent": {"type": "integer", "minimum": 1, "maximum": 100}}},
            "skill": "system", "synthesize": "{direction} el volumen {percent}%"}},
        {"type": "function", "function": {
            "name": "system_power",
            "description": "Apagar, reiniciar, suspender o bloquear el equipo. Siempre pide confirmación después.",
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["apaga", "reinicia", "suspende", "bloquea"]}}},
            "skill": "system", "synthesize": "{action} el equipo"}},
        {"type": "function", "function": {
            "name": "apps_open",
            "description": "Abrir una aplicación por su nombre",
            "parameters": {"type": "object", "properties": {
                "app": {"type": "string", "description": "Nombre de la app"}}, "required": ["app"]},
            "skill": "apps", "synthesize": "abre {app}"}},
        {"type": "function", "function": {
            "name": "apps_close",
            "description": "Cerrar una aplicación por su nombre",
            "parameters": {"type": "object", "properties": {"app": {"type": "string"}}},
            "skill": "apps", "synthesize": "cierra {app}"}},
        {"type": "function", "function": {
            "name": "terminal_run",
            "description": "Ejecutar un comando de terminal seguro y corto",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
            "skill": "terminal", "synthesize": "ejecuta {command}"}},
        {"type": "function", "function": {
            "name": "web_search",
            "description": "Buscar algo en la web",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            "skill": "web", "synthesize": "busca {query}"}},
        {"type": "function", "function": {
            "name": "play_music",
            "description": "Poner una canción o video en YouTube",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            "skill": "media", "synthesize": "pon {query}"}},
        {"type": "function", "function": {
            "name": "ask_time",
            "description": "Decir la hora o fecha actual",
            "parameters": {"type": "object", "properties": {"what": {"type": "string", "enum": ["hora", "fecha"]}}},
            "skill": "clock", "synthesize": "qué {what} es"}},
        {"type": "function", "function": {
            "name": "set_reminder",
            "description": "Crear un recordatorio en N minutos",
            "parameters": {"type": "object", "properties": {
                "minutes": {"type": "integer", "minimum": 1, "maximum": 720},
                "message": {"type": "string"}}},
            "skill": "reminder", "synthesize": "recuérdame en {minutes} minutos {message}"}},
    ]

    @classmethod
    def build_tools(cls) -> list:
        """Schemas limpios para APIs (sin claves internas)."""
        return [{"type": "function", "function": {
            k: v for k, v in t["function"].items() if k not in ("skill", "synthesize")
        }} for t in cls.TOOLS]

    def _sync_provider_state(self) -> None:
        if self.manager is None:
            self.llm_provider = LLMProvider.OFFLINE
            self.client = None
            return
        active = self.manager.active
        mapping = {
            "groq": LLMProvider.GROQ,
            "cerebras": LLMProvider.CEREBRAS,
            "gemini": LLMProvider.GEMINI,
            "openrouter": LLMProvider.OPENROUTER,
            "offline": LLMProvider.OFFLINE,
        }
        self.llm_provider = mapping.get(active, LLMProvider.OFFLINE)
        groq = self.manager.providers.get("groq")
        self.client = getattr(groq, "client", None)

    async def initialize(self) -> bool:
        self.manager = LLMManager(self.config, self.build_tools(), self.TOOLS)
        await self.manager.initialize()
        self._sync_provider_state()
        return True

    async def classify_intent(self, text: str) -> Optional[Intent]:
        try:
            data = await self.manager.call("classify_intent", text) if self.manager else {}
            self._sync_provider_state()
            intent = str(data.get("intent", "") or "").strip()
            confidence = float(data.get("confidence", 0.0) or 0.0)
            params = data.get("parameters", {}) if isinstance(data.get("parameters"), dict) else {}
            min_conf = float(self.config.get("llm.intent_min_confidence", 0.6))
            if intent and confidence >= min_conf:
                return Intent(intent=intent, confidence=confidence, parameters=params)
        except Exception as e:
            logger.debug("classify_intent provider falló: %s", e)
        return self._heuristic_intent_classify(text)

    async def process_with_llm(self, text: str) -> str:
        prompt = (
            "You are Jarvis, a Linux voice assistant. "
            "Respond in Spanish with maximum 1 short sentence.\n"
            f"User: {text}\nResponse:"
        )
        try:
            response = await self.manager.call(
                "generate",
                prompt,
                int(self.config.get("llm.max_tokens", 48)),
                float(self.config.get("llm.temperature", 0.1)),
            ) if self.manager else ""
            self._sync_provider_state()
            if response:
                return str(response).strip()
        except Exception as e:
            logger.debug("process_with_llm provider falló: %s", e)
        return self._mock_cached(text)

    async def process_with_tools(self, text: str):
        """Function-calling: devuelve (skill_name, args, template) o None."""
        # Compat para tests que inyectan cliente Groq fake
        if self.llm_provider == LLMProvider.GROQ and self.client is not None:
            try:
                response = await self.client.chat.completions.create(
                    model=str(self.config.get("llm.groq.model",
                                              self.config.get("llm.model", "llama-3.1-8b-instant"))),
                    messages=[
                        {"role": "system", "content": "Elige una herramienta o ninguna."},
                        {"role": "user", "content": text},
                    ],
                    tools=self.build_tools(),
                    tool_choice="auto",
                    max_tokens=120,
                    temperature=0.0,
                )
                calls = response.choices[0].message.tool_calls
                if not calls:
                    return None
                call = calls[0]
                for tool in self.TOOLS:
                    fn = tool["function"]
                    if fn["name"] == call.function.name:
                        args = _extract_json_object(call.function.arguments or "{}")
                        return fn.get("skill", ""), args, fn.get("synthesize", "")
            except Exception as e:
                logger.debug("process_with_tools compat falló: %s", e)

        try:
            result = await self.manager.call(
                "tool_call", text, self.build_tools(), self.TOOLS
            ) if self.manager else None
            self._sync_provider_state()
            return result
        except Exception as e:
            logger.debug("process_with_tools provider falló: %s", e)
            return None

    async def chat_reply(self, history: list) -> str:
        system = (
            "Eres Jarvis, asistente de voz. Conversa en español, "
            "máximo 2 frases cortas, tono servicial y directo."
        )
        messages = [{"role": "system", "content": system}, *history[-10:]]
        try:
            response = await self.manager.call(
                "chat",
                messages,
                int(self.config.get("llm.chat_max_tokens", 120)),
                float(self.config.get("llm.chat_temperature", 0.4)),
            ) if self.manager else ""
            self._sync_provider_state()
            if response:
                return str(response).strip()
        except Exception as e:
            logger.debug("chat provider falló: %s", e)
        last = next((m["content"] for m in reversed(history)
                     if m.get("role") == "user"), "")
        return self._mock_cached(last or "hola")

    def _heuristic_intent_classify(self, text: str) -> Optional[Intent]:
        """Simple offline heuristics for classification when LLM is unavailable."""
        text_lower = text.lower()

        if "volumen" in text_lower or "sonido" in text_lower or "silencio" in text_lower:
            return Intent(intent="system.volume", confidence=0.9,
                          parameters={"action": "toggle" if "silencio" in text_lower or "mute" in text_lower else "adjust"})
        if "apaga" in text_lower or "apagar" in text_lower:
            return Intent(intent="system.shutdown", confidence=0.9, parameters={})
        if "reinicia" in text_lower or "reiniciar" in text_lower:
            return Intent(intent="system.restart", confidence=0.9, parameters={})
        if "suspende" in text_lower or "suspender" in text_lower:
            return Intent(intent="system.suspend", confidence=0.9, parameters={})
        if "abre" in text_lower or "abrir" in text_lower:
            return Intent(intent="apps.open", confidence=0.8, parameters={})
        if "cierra" in text_lower or "cerrar" in text_lower:
            return Intent(intent="apps.close", confidence=0.8, parameters={})
        if "ejecuta" in text_lower or "corre" in text_lower:
            return Intent(intent="terminal.execute", confidence=0.8, parameters={})
        if "busca" in text_lower or "buscar" in text_lower or "qué es" in text_lower or "que es" in text_lower:
            return Intent(intent="web.search", confidence=0.8, parameters={})
        if "hora" in text_lower or "fecha" in text_lower or "qué día" in text_lower or "que dia" in text_lower:
            return Intent(intent="clock.time", confidence=0.9, parameters={})
        if any(w in text_lower for w in (
            "pausa", "reproduce", "siguiente", "anterior", "sonando", "suena",
            "canción", "cancion", "música", "musica", "youtube", "pon ", "play ")):
            if "abre youtube" in text_lower and not any(w in text_lower for w in ("pon", "play", "reproduce")):
                return Intent(intent="web.search", confidence=0.7, parameters={})
            return Intent(intent="media.control", confidence=0.8, parameters={})
        if any(w in text_lower for w in (
            "vscode", "cursor", "pytest", "unittest", "npm test", "arregla",
            "revisa el repo", "revisa este repo")):
            return Intent(intent="coding.help", confidence=0.85, parameters={})
        if any(w in text_lower for w in (
            "recuérdame", "recuerdame", "temporizador", "avísame", "avisame", "alarma")):
            return Intent(intent="reminder.create", confidence=0.85, parameters={})
        if any(w in text_lower for w in (
            "cierra esto", "esta ventana", "ventana activa", "en qué estoy", "en que estoy")):
            if "captura" in text_lower or "pantallazo" in text_lower:
                return Intent(intent="window.capture", confidence=0.85, parameters={})
            if "cierra" in text_lower or "cerrar" in text_lower:
                return Intent(intent="window.close", confidence=0.85, parameters={})
            return Intent(intent="window.which", confidence=0.8, parameters={})
        if any(w in text_lower for w in (
            "modo trabajo", "modo foco", "modo noche", "cierre del día", "cierre del dia", "rutina")):
            return Intent(intent="routines.run", confidence=0.85, parameters={})
        if text_lower.startswith(("dicta", "escribe", "copia esto", "pega")):
            return Intent(intent="dictation.write", confidence=0.85, parameters={})
        if any(w in text_lower for w in (
            "estado del pc", "estado del equipo", "batería", "bateria", "uso de cpu",
            "espacio en disco", "temperatura", "actualizaciones", "qué consume", "que consume")):
            return Intent(intent="status.report", confidence=0.85, parameters={})
        if any(w in text_lower for w in (
            "qué hiciste", "que hiciste", "historial", "deshaz", "deshacer")):
            return Intent(intent="audit.query", confidence=0.9, parameters={})
        if any(w in text_lower for w in (
            "puertos", "firewall", "seguridad", "ssh", "integridad", "baseline",
            "virus", "antivirus", "sospechoso", "endurec")):
            return Intent(intent="security.check", confidence=0.85, parameters={})
        return None

    def _mock_cached(self, text: str) -> str:
        """Cache en memoria de respuestas mock (TTL corto, máx. N)."""
        import time
        now = time.monotonic()
        hit = self._mock_cache.get(text)
        if hit and now - hit[0] < self._MOCK_CACHE_TTL:
            return hit[1]
        response = self._get_mock_response(text)
        if len(self._mock_cache) >= self._MOCK_CACHE_MAX:
            oldest = min(self._mock_cache, key=lambda k: self._mock_cache[k][0])
            del self._mock_cache[oldest]
        self._mock_cache[text] = (now, response)
        return response

    def _get_mock_response(self, text: str) -> str:
        text_lower = text.lower()
        if "hola" in text_lower or "saludos" in text_lower:
            return "Hola, señor. Listo para recibir instrucciones."
        if "quién eres" in text_lower or "quien eres" in text_lower:
            return "Soy Jarvis, su asistente personal modular para Linux."
        if "gracias" in text_lower:
            return "A su servicio, señor."
        if "que puedes hacer" in text_lower or "qué puedes hacer" in text_lower or "ayuda" in text_lower:
            return ("Puedo subir o bajar el volumen, abrir y cerrar apps, "
                    "ejecutar comandos y buscar en la web. Dime la orden.")
        return f"Entendido, he procesado su petición: '{text}'"

    async def cleanup(self):
        """Clean up LLM resources."""
        if self.manager is not None:
            await self.manager.close()
            self._sync_provider_state()
            logger.info("Brain providers closed")
