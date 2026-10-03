#!/usr/bin/env python3
"""Tests mínimos: router determinista, terminal segura, confirmaciones."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.config import Config
from core.skill_manager import SkillManager
from core.brain import Brain
from core.router import Router
from skills.terminal import TerminalSkill
from skills.system import SystemSkill


def make_router():
    config = Config("config.yaml")
    sm = SkillManager(config)
    brain = Brain(config)
    return Router(sm, brain, config), sm, brain


class TestRouter(unittest.IsolatedAsyncioTestCase):
    async def test_volume_is_deterministic(self):
        router, sm, _ = make_router()
        await sm.load_skills()
        resp = await router.route("sube el volumen")
        self.assertIsInstance(resp, str)
        # Éxito silencioso ("") o aviso de pactl ausente: ambos son ruta determinista
        self.assertTrue(resp == "" or "volumen" in resp.lower() or "pactl" in resp.lower())

    async def test_unknown_falls_back_to_llm(self):
        router, sm, _ = make_router()
        await sm.load_skills()
        resp = await router.route("hola")
        self.assertIsInstance(resp, str)
        self.assertIn("Hola", resp)


class TestTerminal(unittest.IsolatedAsyncioTestCase):
    async def test_safe_pwd(self):
        skill = TerminalSkill()
        result = await skill.execute("ejecuta pwd")
        self.assertIn("response", result)
        self.assertTrue(result["response"].strip() != "")

    async def test_blocked_mkfs_even_with_confirm(self):
        skill = TerminalSkill()
        result = await skill.execute("ejecuta mkfs, confirma")
        self.assertIn("bloqueado", result["response"].lower())

    async def test_dangerous_rm_needs_confirmation(self):
        skill = TerminalSkill()
        result = await skill.execute("ejecuta rm -rf /tmp/test")
        self.assertTrue(result.get("requires_confirmation", False))


class TestSystem(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_requires_confirmation(self):
        skill = SystemSkill()
        result = await skill.execute("apaga el equipo")
        self.assertTrue(result.get("requires_confirmation", False))
        self.assertIn("confirma", result["response"].lower())


class TestClock(unittest.IsolatedAsyncioTestCase):
    async def test_hora(self):
        from skills.clock import ClockSkill
        result = await ClockSkill().execute("qué hora es")
        self.assertIn("Son las", result["response"])

    async def test_fecha(self):
        from skills.clock import ClockSkill
        result = await ClockSkill().execute("qué fecha es")
        self.assertIn("Hoy es", result["response"])


class TestMedia(unittest.IsolatedAsyncioTestCase):
    async def test_sin_playerctl_responde(self):
        import skills.media as media_mod
        from skills.media import MediaSkill
        orig = media_mod.shutil.which
        media_mod.shutil.which = lambda _: None
        try:
            result = await MediaSkill().execute("pausa la música")
        finally:
            media_mod.shutil.which = orig
        self.assertIn("playerctl", result["response"])


class TestReminder(unittest.TestCase):
    def test_parse_delay(self):
        from skills.reminder import ReminderSkill
        self.assertEqual(ReminderSkill.parse_delay("recuérdame en 5 minutos"), 300)
        self.assertEqual(ReminderSkill.parse_delay("avísame en 30 segundos"), 30)
        self.assertEqual(ReminderSkill.parse_delay("pon temporizador de 2 horas"), 7200)
        self.assertIsNone(ReminderSkill.parse_delay("recuérdame algo"))


class TestWeb(unittest.TestCase):
    def test_extract_query(self):
        from skills.web import WebSearchSkill
        skill = WebSearchSkill()
        self.assertEqual(skill._extract_query("busca python async"), "python async")
        self.assertEqual(skill._extract_query("qué es docker"), "docker")
        self.assertTrue(skill._is_definition_question("qué es docker"))
        self.assertFalse(skill._is_definition_question("busca linux"))


if __name__ == "__main__":
    unittest.main()
