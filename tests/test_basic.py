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


class TestSystemExtra(unittest.IsolatedAsyncioTestCase):
    async def test_wifi_off_needs_confirmation(self):
        from skills.system import SystemSkill
        result = await SystemSkill().execute("apaga el wifi")
        self.assertTrue(result.get("requires_confirmation", False))

    async def test_volume_wpctl_backend(self):
        from skills.system import SystemSkill
        from core.platform import PlatformOps
        calls = []

        async def fake_set_volume(percent=None, delta=None):
            calls.append((percent, delta))
            return True

        orig = PlatformOps.set_volume
        PlatformOps.set_volume = staticmethod(fake_set_volume)
        try:
            result = await SystemSkill().execute("sube el volumen")
        finally:
            PlatformOps.set_volume = orig
        self.assertTrue(result.get("silent", False))
        self.assertEqual(calls, [(None, 5)])


class TestAppsExtra(unittest.TestCase):
    def test_extract_url(self):
        from skills.apps import AppsSkill
        self.assertEqual(AppsSkill._extract_url("abre youtube.com"),
                         "https://youtube.com")
        self.assertEqual(AppsSkill._extract_url("abre https://example.org/x"),
                         "https://example.org/x")
        self.assertIsNone(AppsSkill._extract_url("abre firefox"))

    def test_extract_path(self):
        import tempfile
        from pathlib import Path
        from skills.apps import AppsSkill
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = f.name
        try:
            self.assertEqual(AppsSkill._extract_path(f"abre {path}"), path)
        finally:
            Path(path).unlink()
        self.assertIsNone(AppsSkill._extract_path("abre /ruta/que/no/existe"))


class TestWeb(unittest.TestCase):
    def test_extract_query(self):
        from skills.web import WebSearchSkill
        skill = WebSearchSkill()
        self.assertEqual(skill._extract_query("busca python async"), "python async")
        self.assertEqual(skill._extract_query("qué es docker"), "docker")
        self.assertTrue(skill._is_definition_question("qué es docker"))
        self.assertFalse(skill._is_definition_question("busca linux"))


class TestPending(unittest.IsolatedAsyncioTestCase):
    async def test_set_then_cancel(self):
        from core.pending import PendingManager
        pm = PendingManager(timeout_seconds=12)
        called = []
        async def fake():
            called.append(True)
            return {"response": "hecho", "silent": False}
        await pm.set("apagar el equipo", fake)
        self.assertEqual(await pm.handle_reply("cancela"), "Cancelado.")
        self.assertEqual(called, [])
        self.assertIsNone(await pm.peek())

    async def test_set_then_confirm_executes(self):
        from core.pending import PendingManager
        pm = PendingManager(timeout_seconds=12)
        async def fake():
            return {"response": "Apagando.", "silent": False}
        await pm.set("apagar el equipo", fake)
        self.assertEqual(await pm.handle_reply("sí, confirma"), "Apagando.")

    async def test_other_keeps_pending(self):
        from core.pending import PendingManager
        pm = PendingManager(timeout_seconds=12)
        async def fake():
            return {"response": "x", "silent": True}
        await pm.set("reiniciar el equipo", fake)
        reply = await pm.handle_reply("qué hora es")
        self.assertIn("reiniciar el equipo", reply)
        self.assertIsNotNone(await pm.peek())

    async def test_router_shutdown_asks_and_cancels(self):
        router, sm, _ = make_router()
        await sm.load_skills()
        first = await router.route("apaga el equipo")
        self.assertIn("confirma o cancela", first)
        self.assertEqual(await router.route("no"), "Cancelado.")


class TestRoutines(unittest.IsolatedAsyncioTestCase):
    async def test_rutina_lists_names(self):
        from skills.routines import RoutinesSkill
        result = await RoutinesSkill().execute("rutina")
        for name in ("trabajo", "foco", "cierre", "noche"):
            self.assertIn(name, result["response"])


class TestAudit(unittest.TestCase):
    def test_log_and_recent(self):
        import tempfile
        from pathlib import Path
        from core.audit import AuditLog, AuditEntry
        path = Path(tempfile.mkdtemp()) / "audit.log"
        log = AuditLog(path=path, enabled=True)
        log.log(AuditEntry(ts=1000.0, skill="system", text="sube el volumen",
                           action="system.volume", result=""))
        recent = log.recent(3)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].action, "system.volume")
        self.assertTrue(path.exists())

    def test_undo_empty(self):
        import asyncio
        from core.audit import AuditLog
        log = AuditLog(enabled=False)
        self.assertIn("nada que deshacer", asyncio.run(log.undo_last()))


class TestWindowSkill(unittest.IsolatedAsyncioTestCase):
    async def test_que_ventana_responds(self):
        from skills.window import WindowSkill
        result = await WindowSkill().execute("qué ventana es esta")
        self.assertIn("response", result)
        self.assertTrue(str(result["response"]).strip() != "")


class TestDictation(unittest.IsolatedAsyncioTestCase):
    async def test_dicta_sin_texto_pide_texto(self):
        from skills.dictation import DictationSkill
        result = await DictationSkill().execute("dicta")
        self.assertIn("Qué texto", result["response"])

    def test_extract_payload(self):
        from skills.dictation import DictationSkill
        self.assertEqual(DictationSkill.extract_payload("dicta compra leche"),
                         "compra leche")
        self.assertEqual(DictationSkill.extract_payload("dicta"), "")


class TestConfigRoutines(unittest.TestCase):
    def test_modo_fiesta_tiene_url_y_app(self):
        from skills.routines import RoutinesSkill
        RoutinesSkill.config = None  # defaults en código
        skill = RoutinesSkill()
        routines = skill._routines()
        self.assertIn("modo_fiesta", routines)
        actions = [s.get("action") for s in routines["modo_fiesta"]["steps"]]
        self.assertIn("open_url", actions)
        self.assertIn("open_app", actions)

    def test_rutinas_desde_config(self):
        from skills.routines import RoutinesSkill
        from utils.config import Config

        class FakeConfig:
            def get(self, key, default=None):
                if key == "routines":
                    return {"fiesta_test": {
                        "triggers": ["fiesta test"],
                        "steps": [{"action": "notify", "message": "x"}]}}
                if key == "apps_map":
                    return {}
                if key == "clap":
                    return {}
                return default

        RoutinesSkill.config = FakeConfig()
        try:
            routines = RoutinesSkill()._routines()
            self.assertIn("fiesta_test", routines)
            self.assertIn("modo_fiesta", routines)  # defaults siguen
        finally:
            RoutinesSkill.config = None


class TestClap(unittest.TestCase):
    def test_doble_aplauso_dispara(self):
        from core.clap_detector import ClapConfig, ClapDetector
        det = ClapDetector(ClapConfig(energy_threshold=2500, min_gap_ms=120,
                                      max_gap_ms=900, cooldown_s=3))
        quiet = [0] * 64
        clap = [3000] * 64
        self.assertFalse(det.feed(quiet, now=0.0))
        self.assertFalse(det.feed(clap, now=0.1))   # primer aplauso
        self.assertFalse(det.feed(quiet, now=0.2))
        self.assertTrue(det.feed(clap, now=0.4))    # segundo: dispara
        self.assertFalse(det.feed(clap, now=0.5))   # cooldown: no re-dispara

    def test_aplauso_aislado_no_dispara(self):
        from core.clap_detector import ClapConfig, ClapDetector
        det = ClapDetector(ClapConfig())
        self.assertFalse(det.feed([3000] * 64, now=0.0))
        self.assertFalse(det.feed([0] * 64, now=2.0))  # fuera de ventana


class TestPlatformOps(unittest.IsolatedAsyncioTestCase):
    async def test_linux_open_app_inexistente_falla(self):
        import core.platform as plat
        if plat.IS_WINDOWS:
            self.skipTest("solo Linux")
        self.assertFalse(await plat.PlatformOps.open_app("cmd_inexistente_xyz"))

    async def test_windows_backend_seleccionado(self):
        import core.platform as plat
        orig_win, orig_sh = plat.IS_WINDOWS, plat._sh
        calls = []

        async def fake_sh(cmd, timeout=8.0):
            calls.append(cmd)
            return 0, ""

        plat.IS_WINDOWS = True
        plat._sh = fake_sh
        try:
            self.assertTrue(await plat.PlatformOps.open_app("whatever"))
            self.assertTrue(any("cmd /c start" in c for c in calls))
        finally:
            plat.IS_WINDOWS = orig_win
            plat._sh = orig_sh


class TestClapTrigger(unittest.IsolatedAsyncioTestCase):
    async def test_simular_aplauso_ejecuta_rutina(self):
        from skills.routines import RoutinesSkill
        from core.platform import PlatformOps
        calls = []

        async def fake_url(url):
            calls.append(("open_url", url))
            return True

        async def fake_app(app):
            calls.append(("open_app", app))
            return True

        async def fake_vol(percent=None, delta=None):
            calls.append(("volume", percent))
            return True

        async def fake_notify(title, message):
            calls.append(("notify", message))
            return True

        orig = (PlatformOps.open_url, PlatformOps.open_app,
                PlatformOps.set_volume, PlatformOps.notify)
        PlatformOps.open_url = staticmethod(fake_url)
        PlatformOps.open_app = staticmethod(fake_app)
        PlatformOps.set_volume = staticmethod(fake_vol)
        PlatformOps.notify = staticmethod(fake_notify)

        class FakeConfig:
            def get(self, key, default=None):
                if key == "clap":
                    return {"routine": "modo_fiesta"}
                if key in ("routines", "apps_map"):
                    return {}
                return default

        RoutinesSkill.config = FakeConfig()
        try:
            result = await RoutinesSkill().execute("simular aplauso")
        finally:
            (PlatformOps.open_url, PlatformOps.open_app,
             PlatformOps.set_volume, PlatformOps.notify) = orig
            RoutinesSkill.config = None
        kinds = [c[0] for c in calls]
        self.assertIn("open_url", kinds)
        self.assertIn("open_app", kinds)
        self.assertEqual(result.get("silent"), True)


if __name__ == "__main__":
    unittest.main()
