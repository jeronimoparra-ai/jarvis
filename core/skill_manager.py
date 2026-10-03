#!/usr/bin/env python3
"""
Skill manager for Jarvis - Loads and manages skills

Skills are Python modules that define specific capabilities.
Each skill should:
1. Define patterns to match user commands
2. Implement an execute method
3. Return response (can be empty for silent execution)
"""

import asyncio
import importlib
import logging
import inspect
from pathlib import Path
from typing import Dict, Any, Optional, List, Type

from utils.config import Config
from skills.base import Skill

logger = logging.getLogger(__name__)

class SkillManager:
    """Manages loading and execution of skills"""
    
    def __init__(self, config: Config):
        self.config = config
        self.skills: Dict[str, Skill] = {}
        
    async def load_skills(self) -> None:
        """
        Load all enabled skills from skills directory
        
        Each skill is a Python file that:
        - Inherits from Skill base class
        - Has a patterns list
        - Has an execute method
        """
        # Resolve skills directory relative to the project root
        skills_dir = self.config.get('skills.directory', 'skills')
        skills_path = Path(skills_dir)
        if not skills_path.is_absolute():
            # Assume relative to the script's directory (parent of core/)
            skills_path = Path(__file__).resolve().parent.parent / skills_path
            
        if not skills_path.exists():
            logger.warning(f"Skills directory not found: {skills_path}")
            return
            
        enabled_skills = self.config.get('skills.enabled', ['system', 'apps', 'terminal', 'web'])
        
        for skill_file in skills_path.glob('*.py'):
            if skill_file.name.startswith('_') or skill_file.name == 'base.py':
                continue
                
            skill_name = skill_file.stem
            if skill_name not in enabled_skills:
                continue
                
            try:
                # Import skill module
                module = importlib.import_module(f'skills.{skill_name}')
                
                # Find skill classes
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, Skill) and obj is not Skill:
                        # Instantiate skill
                        skill_instance = obj()
                        self.skills[skill_name] = skill_instance
                        logger.info(f"Loaded skill: {skill_name}")
                        break
                        
            except Exception as e:
                logger.error(f"Failed to load skill {skill_name}: {e}")
                
    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name"""
        return self.skills.get(name)
        
    def get_skill_by_intent(self, intent: str) -> Optional[Skill]:
        """
        Find skill that handles specific intent
        
        Args:
            intent: Intent string (e.g., 'system.volume')
            
        Returns:
            Skill instance or None
        """
        skill_name = intent.split('.')[0]
        return self.skills.get(skill_name)
        
    async def reload_skill(self, skill_name: str) -> bool:
        """
        Reload a single skill
        
        Args:
            skill_name: Name of skill to reload
            
        Returns:
            True if reload successful
        """
        if skill_name not in self.skills:
            # Try to load new skill
            await self.load_skills()
            return skill_name in self.skills
            
        try:
            # Remove from skills dict
            del self.skills[skill_name]
            
            # Reload
            await self.load_skills()
            
            return skill_name in self.skills
            
        except Exception as e:
            logger.error(f"Failed to reload skill {skill_name}: {e}")
            return False
            
    def list_skills(self) -> List[str]:
        """List all loaded skill names"""
        return list(self.skills.keys())
