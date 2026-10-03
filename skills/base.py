#!/usr/bin/env python3
"""
Base skill class for Jarvis skills

All skills should inherit from this class.

A skill defines:
- patterns: List of patterns to match user commands (regex or keyword strings)
  - String keywords: "abre navegador" → matches if all keywords present
  - Wildcards: "abre *" → matches "abre firefox", "abre vscode"
  - Regex patterns: "/abre (el|la) navegador/i" → regex match
- intent: Intent identifier for this skill
- silent: Whether to respond (True = no verbal response)
"""

import logging
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class Skill(ABC):
    """Base class for all Jarvis skills"""
    
    # Patterns to match user commands (class attribute)
    patterns: List[str] = []
    
    # Intent identifier (class attribute)
    intent: str = ""
    
    # Default response behavior - silence TTS (class attribute)
    silent: bool = False
    
    # Whether this skill can be invoked by LLM (class attribute)
    llm_enabled: bool = True
    
    @abstractmethod
    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute the skill's action
        
        Args:
            text: The original user command
            intent: Optional intent classification result
            
        Returns:
            Dictionary with:
            - response: Response string (can be empty)
            - silent: Whether to suppress TTS (override self.silent)
            - error: Error message if action failed
        """
        pass
