#!/usr/bin/env python3
"""
Web search skill for Jarvis

Handles:
- Quick web searches
- Opening search results in browser

Commands recognized:
- "busca python async"          -> abre búsqueda en el navegador (silencioso)
- "buscar información sobre linux" -> abre búsqueda en el navegador
- "qué es docker"               -> responde resumen breve de Wikipedia + abre navegador
"""

import asyncio
import json
import logging
import urllib.parse
import urllib.request
import webbrowser
from typing import Dict, Any, Optional

from skills.base import Skill

logger = logging.getLogger(__name__)

class WebSearchSkill(Skill):
    """Búsqueda web rápida"""
    
    patterns = ["busca", "buscar", "qué es", "qué es", "cuál es", "cómo es"]
    
    intent = "web"
    
    def __init__(self):
        super().__init__()
        self.silent = True
        
    async def execute(self, text: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute web search
        
        Args:
            text: User command text
            
        Returns:
            Dict with response
        """
        query = self._extract_query(text)
        if not query:
            return {"response": "No entendí la búsqueda.", "silent": False}

        is_definition = self._is_definition_question(text)
        summary = await self._wiki_summary(query) if is_definition else None

        try:
            from urllib.parse import quote_plus
            search_url = f"https://duckduckgo.com/?q={quote_plus(query)}"
            webbrowser.open(search_url)
        except Exception as e:
            logger.error(f"Web search error: {e}")
            if summary:
                return {"response": summary, "silent": False}
            return {"response": "Error en la búsqueda.", "silent": False}

        # "qué es X": respuesta breve hablada + navegador abierto
        if summary:
            return {"response": summary, "silent": False}
        return {"response": "", "silent": True}

    @staticmethod
    def _is_definition_question(text: str) -> bool:
        low = text.lower().strip()
        return low.startswith(("qué es", "que es", "cuál es", "cual es",
                               "quién es", "quien es", "cómo es", "como es"))

    async def _wiki_summary(self, query: str) -> Optional[str]:
        """Resumen de 1 frase desde Wikipedia (es). Sin red -> None."""
        def _fetch() -> Optional[str]:
            try:
                title = urllib.parse.quote(query.strip())
                url = (f"https://es.wikipedia.org/api/rest_v1/page/summary/{title}")
                req = urllib.request.Request(
                    url, headers={"User-Agent": "JarvisVoice/0.1 (Linux)"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    # Límite de bytes: no leer respuestas gigantes
                    data = json.loads(resp.read(65536).decode("utf-8"))
                extract = (data.get("extract") or "").strip()
                if not extract:
                    return None
                # Primera frase, máx ~220 caracteres
                first = extract.split(". ")[0].strip()
                if not first.endswith("."):
                    first += "."
                return first[:220]
            except Exception as e:
                logger.debug("Wikipedia sin resultado para '%s': %s", query, e)
                return None
        return await asyncio.to_thread(_fetch)
            
    def _extract_query(self, text: str) -> Optional[str]:
        """
        Extract search query from text
        
        Args:
            text: User text (can be lowercase)
            
        Returns:
            Query string or None
        """
        text_lower = text.lower().strip()
        
        # Match patterns
        prefixes = ['busca ', 'buscar ', 'qué es ', 'qué es', 'cuál es ', 'cómo es ']
        
        for prefix in prefixes:
            if text_lower.startswith(prefix):
                query = text[len(prefix):].strip()
                return query
                
        # If starts with question words, use the whole text
        if any(text_lower.startswith(w) for w in ['qué ', 'cómo ', 'cuándo ', 'por qué ', 'quién ']):
            return text.strip()
            
        return None
