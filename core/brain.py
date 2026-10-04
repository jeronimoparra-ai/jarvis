#!/usr/bin/env python3
"""
Brain for Jarvis - LLM processing and intent classification

This module handles:
1. Fallback LLM processing when rules don't match
2. Intent classification
3. Tool calling / mock routing

Supports:
- Groq (primary)
- Ollama (fallback/local)
- Mock fallback (offline/no API key)
"""

import asyncio
import logging
import json
import os
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from enum import Enum

from utils.config import Config

logger = logging.getLogger(__name__)

class LLMProvider(Enum):
    GROQ = "groq"
    OLLAMA = "ollama"
    MOCK = "mock"

@dataclass
class Intent:
    """Classified intent result"""
    intent: str
    confidence: float
    parameters: Dict[str, Any]

class Brain:
    """LLM brain for Jarvis - handles fallback reasoning"""
    
    def __init__(self, config: Config):
        self.config = config
        self.llm_provider: LLMProvider = LLMProvider.MOCK
        self.client = None
        
    async def initialize(self) -> bool:
        """Initialize LLM provider"""
        provider = self.config.get('llm.provider', 'groq')
        api_key = self.config.get('llm.api_key', '')
        
        # Check if API Key is a placeholder
        if provider == 'groq' and (not api_key or api_key == 'YOUR_API_KEY'):
            logger.warning("GROQ_API_KEY no está configurada o es el marcador por defecto. Probando Ollama...")
            provider = 'ollama'
            
        if provider == 'groq':
            success = await self._init_groq(api_key)
            if success:
                return True
            # Fallback to ollama
            provider = 'ollama'
            
        if provider == 'ollama':
            success = await self._init_ollama()
            if success:
                return True
                
        # Mock fallback
        logger.warning("No se pudo inicializar ningún LLM real (Groq u Ollama). Usando modo simulación/offline.")
        self.llm_provider = LLMProvider.MOCK
        return True
        
    async def _init_groq(self, api_key: str) -> bool:
        """Initialize Groq client"""
        try:
            from groq import AsyncGroq
            self.client = AsyncGroq(api_key=api_key)
            self.llm_provider = LLMProvider.GROQ
            logger.info("Groq initialized successfully")
            return True
        except ImportError:
            logger.warning("Librería 'groq' no instalada.")
            return False
        except Exception as e:
            logger.warning(f"No se pudo iniciar el cliente de Groq: {e}")
            return False
            
    async def _init_ollama(self) -> bool:
        """Initialize Ollama client connection"""
        try:
            import aiohttp
            # Test local Ollama endpoint
            self.client = aiohttp.ClientSession()
            self.llm_provider = LLMProvider.OLLAMA
            logger.info("Ollama client session initialized")
            return True
        except ImportError:
            logger.warning("Librería 'aiohttp' no instalada.")
            return False
        except Exception as e:
            logger.warning(f"No se pudo iniciar sesión con Ollama: {e}")
            return False
            
    async def classify_intent(self, text: str) -> Optional[Intent]:
        """
        Classify user intent using LLM
        
        Args:
            text: User's command
            
        Returns:
            Classified intent or None
        """
        prompt = f"""
        Classify the intent of this Spanish command:
        "{text}"
        
        Return strictly JSON format:
        {{
            "intent": "system.restart|system.shutdown|system.volume|apps.open|apps.close|web.search|terminal.execute|clock.time|media.control|reminder.create|window.close|window.which|window.capture|routines.run|dictation.write|status.report|audit.query|unknown",
            "confidence": 0.0-1.0,
            "parameters": {{
                // Extract relevant parameters (e.g., volume level, app name, search query)
            }}
        }}
        """
        
        try:
            if self.llm_provider == LLMProvider.GROQ:
                response = await self.client.chat.completions.create(
                    model=self.config.get('llm.model', 'llama3-70b-8192'),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=100,
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )
                
                content = response.choices[0].message.content
                data = json.loads(content)
                
                if data.get('confidence', 0) > 0.6:
                    return Intent(
                        intent=data['intent'],
                        confidence=data['confidence'],
                        parameters=data.get('parameters', {})
                    )
                    
            elif self.llm_provider == LLMProvider.OLLAMA:
                async with self.client.post(
                    'http://localhost:11434/api/generate',
                    json={
                        'model': self.config.get('llm.ollama_model', 'llama3'),
                        'prompt': prompt,
                        'stream': False,
                        'options': {
                            'temperature': 0.1,
                            'num_predict': 100
                        }
                    }
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data.get('response', '')
                        parsed = json.loads(content)
                        
                        if parsed.get('confidence', 0) > 0.6:
                            return Intent(
                                intent=parsed['intent'],
                                confidence=parsed['confidence'],
                                parameters=parsed.get('parameters', {})
                            )
                            
        except Exception as e:
            if self._is_auth_error(e):
                self._downgrade_to_mock("API key rechazada (401)")
            else:
                logger.error(f"Intent classification failed: {e}")

        # Fallback offline simulation/heuristics for intent
        return self._heuristic_intent_classify(text)

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        """Detecta errores de autenticación (key inválida/expirada)."""
        msg = str(exc).lower()
        return any(k in msg for k in (
            "invalid_api_key", "invalid api key", "401",
            "authentication_error", "unauthorized",
        ))

    def _downgrade_to_mock(self, reason: str) -> None:
        """Baja a modo offline tras un fallo de auth. Avisa una sola vez."""
        if self.llm_provider != LLMProvider.MOCK:
            logger.warning(
                "%s. Revisa GROQ_API_KEY en .env (consigue una gratis en "
                "https://console.groq.com/keys) o usa Ollama local. "
                "Sigo en modo offline.", reason)
            self.llm_provider = LLMProvider.MOCK
            if self.client is not None:
                try:
                    close = getattr(self.client, "close", None)
                    if close is not None:
                        result = close()
                        if asyncio.iscoroutine(result):
                            asyncio.get_running_loop().create_task(result)
                except Exception:
                    pass
                finally:
                    self.client = None
        
    def _heuristic_intent_classify(self, text: str) -> Optional[Intent]:
        """Simple offline heuristics for classification when LLM is unavailable"""
        text_lower = text.lower()
        
        # Volume
        if "volumen" in text_lower or "sonido" in text_lower or "silencio" in text_lower:
            return Intent(intent="system.volume", confidence=0.9, parameters={"action": "toggle" if "silencio" in text_lower or "mute" in text_lower else "adjust"})
            
        # Power
        if "apaga" in text_lower or "apagar" in text_lower:
            return Intent(intent="system.shutdown", confidence=0.9, parameters={})
        if "reinicia" in text_lower or "reiniciar" in text_lower:
            return Intent(intent="system.restart", confidence=0.9, parameters={})
        if "suspende" in text_lower or "suspender" in text_lower:
            return Intent(intent="system.suspend", confidence=0.9, parameters={})
            
        # Apps
        if "abre" in text_lower or "abrir" in text_lower:
            return Intent(intent="apps.open", confidence=0.8, parameters={})
        if "cierra" in text_lower or "cerrar" in text_lower:
            return Intent(intent="apps.close", confidence=0.8, parameters={})
            
        # Terminal
        if "ejecuta" in text_lower or "corre" in text_lower:
            return Intent(intent="terminal.execute", confidence=0.8, parameters={})
            
        # Web
        if "busca" in text_lower or "buscar" in text_lower or "qué es" in text_lower:
            return Intent(intent="web.search", confidence=0.8, parameters={})

        # Hora / fecha
        if "hora" in text_lower or "fecha" in text_lower or "qué día" in text_lower:
            return Intent(intent="clock.time", confidence=0.9, parameters={})

        # Multimedia
        if any(w in text_lower for w in ("pausa", "reproduce", "siguiente",
               "anterior", "sonando", "suena", "canción", "música")):
            return Intent(intent="media.control", confidence=0.8, parameters={})

        # Recordatorios
        if any(w in text_lower for w in ("recuérdame", "recuerdame", "temporizador",
               "avísame", "avisame", "alarma")):
            return Intent(intent="reminder.create", confidence=0.85, parameters={})

        # Ventana activa
        if any(w in text_lower for w in ("cierra esto", "esta ventana",
               "ventana activa", "en qué estoy", "en que estoy")):
            if "captura" in text_lower or "pantallazo" in text_lower:
                return Intent(intent="window.capture", confidence=0.85, parameters={})
            if "cierra" in text_lower or "cerrar" in text_lower:
                return Intent(intent="window.close", confidence=0.85, parameters={})
            return Intent(intent="window.which", confidence=0.8, parameters={})

        # Rutinas
        if any(w in text_lower for w in ("modo trabajo", "modo foco", "modo noche",
               "cierre del día", "cierre del dia", "rutina")):
            return Intent(intent="routines.run", confidence=0.85, parameters={})

        # Dictado
        if text_lower.startswith(("dicta", "escribe", "copia esto", "pega")):
            return Intent(intent="dictation.write", confidence=0.85, parameters={})

        # Estado del sistema
        if any(w in text_lower for w in ("estado del pc", "estado del equipo",
               "batería", "bateria", "uso de cpu", "espacio en disco",
               "temperatura", "actualizaciones", "qué consume")):
            return Intent(intent="status.report", confidence=0.85, parameters={})

        # Historial / deshacer
        if any(w in text_lower for w in ("qué hiciste", "que hiciste", "historial",
               "deshaz", "deshacer")):
            return Intent(intent="audit.query", confidence=0.9, parameters={})

        return None

    async def process_with_llm(self, text: str) -> str:
        """
        Process text with LLM for general responses
        
        Args:
            text: User's command
            
        Returns:
            LLM response (max 1 sentence)
        """
        prompt = f"""
        You are Jarvis, a voice assistant for Linux. 
        Respond in Spanish with maximum 1 sentence, very brief and direct.
        
        User: {text}
        
        Response:"""
        
        try:
            if self.llm_provider == LLMProvider.GROQ:
                response = await self.client.chat.completions.create(
                    model=self.config.get('llm.model', 'llama3-70b-8192'),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.config.get('llm.max_tokens', 50),
                    temperature=self.config.get('llm.temperature', 0.1)
                )
                return response.choices[0].message.content.strip()
                
            elif self.llm_provider == LLMProvider.OLLAMA:
                async with self.client.post(
                    'http://localhost:11434/api/generate',
                    json={
                        'model': self.config.get('llm.ollama_model', 'llama3'),
                        'prompt': prompt,
                        'stream': False,
                        'options': {
                            'temperature': self.config.get('llm.temperature', 0.1),
                            'num_predict': self.config.get('llm.max_tokens', 50)
                        }
                    }
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('response', '').strip()
                        
        except Exception as e:
            if self._is_auth_error(e):
                self._downgrade_to_mock("API key rechazada (401)")
            else:
                logger.error(f"LLM processing failed: {e}")

        # Mock responses
        return self._get_mock_response(text)
        
    def _get_mock_response(self, text: str) -> str:
        """Return smart mock responses offline"""
        text_lower = text.lower()
        if "hola" in text_lower or "saludos" in text_lower:
            return "Hola, señor. Listo para recibir instrucciones."
        if "quién eres" in text_lower:
            return "Soy Jarvis, su asistente personal modular para Linux."
        if "gracias" in text_lower:
            return "A su servicio, señor."
        if "que puedes hacer" in text_lower or "qué puedes hacer" in text_lower or "ayuda" in text_lower:
            return ("Puedo subir o bajar el volumen, abrir y cerrar apps, "
                    "ejecutar comandos y buscar en la web. Dime la orden.")
            
        return f"Entendido, he procesado su petición: '{text}'"
        
    async def cleanup(self):
        """Clean up LLM resources"""
        if self.client and hasattr(self.client, 'close'):
            await self.client.close()
            logger.info("Brain client closed")
