#!/usr/bin/env python3
"""
Configuration manager for Jarvis

Loads and manages configuration from YAML file and environment variables.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class Config:
    """Configuration manager"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self._load_env()
        self._load()
        self._apply_env_overrides()
        
    def _load_env(self) -> None:
        """Load .env file if it exists (cwd o junto al config)"""
        candidates = [Path(".env")]
        try:
            candidates.append(Path(self.config_path).parent / ".env")
        except Exception:
            pass
        env_path = next((p for p in candidates if p.exists()), Path(".env"))
        if env_path.exists():
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, val = line.split('=', 1)
                            # Remove quotes if present
                            val = val.strip().strip('"').strip("'")
                            os.environ[key.strip()] = val
                logger.info("Variables de entorno cargadas desde .env")
            except Exception as e:
                logger.error(f"Error cargando .env: {e}")

    def _load(self) -> None:
        """Load configuration from file"""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            self.config = {}
            return
            
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
                
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self.config = {}
            
    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to config"""
        # Provider API keys
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            self.set("llm.groq.api_key", groq_key)
            self.set("llm.api_key", groq_key)  # compat legado
        cerebras_key = os.getenv("CEREBRAS_API_KEY")
        if cerebras_key:
            self.set("llm.cerebras.api_key", cerebras_key)
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            self.set("llm.gemini.api_key", gemini_key)
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            self.set("llm.openrouter.api_key", openrouter_key)
            
        # Override Provider
        llm_provider = os.getenv("LLM_PROVIDER")
        if llm_provider:
            self.set("llm.provider", llm_provider)
        llm_model = os.getenv("LLM_MODEL")
        if llm_model:
            # Modelo del proveedor primario actual (compat básica)
            provider = str(self.get("llm.provider", "groq") or "groq").lower()
            self.set(f"llm.{provider}.model", llm_model)

        # Override Wake Word Engine
        ww_engine = os.getenv("WAKE_WORD_ENGINE")
        if ww_engine:
            self.set("wake_word.engine", ww_engine)

        # Override STT Model Size
        stt_model = os.getenv("STT_MODEL_SIZE")
        if stt_model:
            self.set("stt.model_size", stt_model)
        stt_device = os.getenv("STT_DEVICE")
        if stt_device:
            self.set("stt.device", stt_device)
        stt_compute = os.getenv("STT_COMPUTE_TYPE")
        if stt_compute:
            self.set("stt.compute_type", stt_compute)
            
    def get(self, key: str, default: Any = None) -> Any:
        """Get config value by key (supports dot notation)"""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
                
        return value
        
    def set(self, key: str, value: Any) -> None:
        """Set config value by key (supports dot notation)"""
        keys = key.split('.')
        config = self.config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
            
        config[keys[-1]] = value
        
    def save(self) -> None:
        """Save config to file"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False)
                
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
