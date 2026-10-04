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
        self.assertIn("play_youtube", actions)
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


class TestChatMode(unittest.IsolatedAsyncioTestCase):
    async def test_entrar_y_salir(self):
        from skills.chat import ChatSkill
        from core.chat import ChatSession
        session = ChatSession()
        ChatSkill.session = session
        try:
            r1 = await ChatSkill().execute("modo chat")
            self.assertTrue(session.active)
            self.assertIn("chat", r1["response"].lower())
            r2 = await ChatSkill().execute("modo tareas")
            self.assertFalse(session.active)
            self.assertIn("tareas", r2["response"].lower())
        finally:
            ChatSkill.session = None

    async def test_router_conversa_en_modo_chat(self):
        from skills.chat import ChatSkill
        router, sm, _ = make_router()
        await sm.load_skills()
        if sm.get_skill("chat") is None:
            self.skipTest("skill chat no cargada")
        ChatSkill.session = router.chat_session
        try:
            await router.route("modo chat")
            reply = await router.route("cuéntame algo")
            self.assertTrue(isinstance(reply, str) and len(reply) > 0)
            await router.route("modo tareas")
            self.assertFalse(router.chat_session.active)
        finally:
            ChatSkill.session = None

    async def test_chat_respeta_exit_aunque_matchee(self):
        # "modo tareas" sale incluso con sesión activa
        from skills.chat import ChatSkill
        router, sm, _ = make_router()
        await sm.load_skills()
        ChatSkill.session = router.chat_session
        try:
            await router.route("modo chat")
            out = await router.route("modo tareas")
            self.assertIn("tareas", out.lower())
        finally:
            ChatSkill.session = None


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


class TestFiestaPorVoz(unittest.IsolatedAsyncioTestCase):
    async def test_modo_fiesta_por_voz(self):
        # "modo fiesta" hablado ejecuta la rutina (sin aplausos)
        from skills.routines import RoutinesSkill
        from core.platform import PlatformOps
        import skills.media as media_mod
        calls = []
        orig_assist = media_mod.assist_youtube_play
        orig_wait = media_mod.youtube_load_wait

        async def fake_assist(url, config=None, is_search=True):
            calls.append(("assist", url))
            return True

        media_mod.assist_youtube_play = fake_assist
        media_mod.youtube_load_wait = lambda config=None, default=3.5: 0

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
                if key in ("routines", "apps_map", "clap"):
                    return {}
                return default

        RoutinesSkill.config = FakeConfig()
        try:
            result = await RoutinesSkill().execute("modo fiesta")
        finally:
            (PlatformOps.open_url, PlatformOps.open_app,
             PlatformOps.set_volume, PlatformOps.notify) = orig
            media_mod.assist_youtube_play = orig_assist
            media_mod.youtube_load_wait = orig_wait
            RoutinesSkill.config = None
        kinds = [c[0] for c in calls]
        self.assertIn("open_url", kinds)  # play_youtube abre la URL
        self.assertIn("assist", kinds)
        self.assertIn("volume", kinds)
        self.assertIn("audit_action", result)


class TestMediaPlay(unittest.TestCase):
    def test_parse_query(self):
        from skills.media import extract_play_query
        self.assertEqual(extract_play_query("pon bohemian rhapsody"),
                         "bohemian rhapsody")
        self.assertEqual(extract_play_query("reproduce despacito en youtube"),
                         "despacito")
        self.assertEqual(extract_play_query("play lo-fi hip hop radio"),
                         "lo-fi hip hop radio")

    def test_build_search_url(self):
        from skills.media import build_youtube_url
        url = build_youtube_url("bohemian rhapsody")
        self.assertTrue(url.startswith(
            "https://www.youtube.com/results?search_query="))
        self.assertIn("bohemian+rhapsody", url)
        watch = "https://www.youtube.com/watch?v=abc123"
        self.assertEqual(build_youtube_url(watch), watch)

    def test_abre_youtube_solo_abre(self):
        from skills.media import wants_youtube_play
        self.assertFalse(wants_youtube_play("abre youtube"))
        self.assertTrue(wants_youtube_play("pon despacito"))
        self.assertTrue(wants_youtube_play("abre youtube y pon despacito"))


class TestCoding(unittest.IsolatedAsyncioTestCase):
    async def test_whitelist_bloquea_rm(self):
        from skills.coding import CodingSkill
        # rm -rf es destructivo: no se ejecuta, va a pending con confirma
        result = await CodingSkill().execute("ejecuta rm -rf /tmp/x")
        self.assertTrue(result.get("requires_confirmation", False))
        result2 = await CodingSkill().execute("ejecuta sudo rm -rf /")
        self.assertTrue(result2.get("requires_confirmation", False))

    async def test_whitelist_permite_git_status(self):
        from skills.coding import CodingSkill
        result = await CodingSkill().execute("git status")
        self.assertIn("git status", result["response"])

    async def test_destructivo_pide_confirmacion(self):
        from skills.coding import CodingSkill
        result = await CodingSkill().execute("ejecuta git push --force")
        self.assertTrue(result.get("requires_confirmation", False))
        self.assertIn("deferred_execute", result)

    def test_git_root_mock(self):
        import tempfile
        from pathlib import Path
        from skills.coding import CodingSkill
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".git").mkdir()
            sub = Path(tmp) / "sub" / "dir"
            sub.mkdir(parents=True)
            self.assertEqual(CodingSkill.git_root(sub), Path(tmp).resolve())


class TestInputControl(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_no_mueve(self):
        from core.input_control import InputControl

        class FakeConfig:
            def get(self, key, default=None):
                return {"input_control.enabled": False}.get(key, default)

        ctl = InputControl(FakeConfig())
        self.assertFalse(await ctl.move_to(100, 100))
        self.assertFalse(await ctl.type_text("hola"))

    def test_typing_bloquea_peligroso(self):
        from core.input_control import InputControl
        self.assertFalse(InputControl._typing_safe("rm -rf /"))
        self.assertTrue(InputControl._typing_safe("hola mundo"))


class TestCompoundRouting(unittest.IsolatedAsyncioTestCase):
    async def test_abre_vscode_y_tests_va_a_coding(self):
        router, sm, _ = make_router()
        await sm.load_skills()
        # Debe preferir el patrón largo de coding sobre "abre" de apps
        skill_names = []
        orig = sm.skills.get("coding")
        if orig is None:
            self.skipTest("skill coding no cargada")
        import unittest.mock as mock
        responses = []

        async def spy_execute(text, intent=None):
            responses.append(text)
            return {"response": "spy", "silent": False, "no_audit": True}

        with mock.patch.object(orig, "execute", spy_execute):
            await router.route("abre vscode y ejecuta los tests")
        self.assertTrue(responses)


class TestWindowsPaths(unittest.IsolatedAsyncioTestCase):
    def _patch_win(self):
        import core.platform as plat
        import core.input_control as ic
        saved = {"win": plat.IS_WINDOWS, "sh": plat._sh,
                 "ic_win": ic.IS_WINDOWS}
        cmds = []

        async def fake_sh(cmd, timeout=8.0):
            cmds.append(cmd)
            return 0, ""

        plat.IS_WINDOWS = True
        plat._sh = fake_sh
        ic.IS_WINDOWS = True

        def restore():
            plat.IS_WINDOWS = saved["win"]
            plat._sh = saved["sh"]
            ic.IS_WINDOWS = saved["ic_win"]

        return restore, cmds

    async def test_right_click_flags(self):
        from core.input_control import InputControl
        restore, cmds = self._patch_win()
        try:
            self.assertTrue(await InputControl().click("right"))
        finally:
            restore()
        ps = " ".join(cmds)
        self.assertIn("mouse_event(8,", ps)   # RIGHTDOWN
        self.assertIn("mouse_event(16,", ps)  # RIGHTUP (no 8 repetido)

    async def test_hotkey_ctrl_l(self):
        from core.input_control import InputControl
        restore, cmds = self._patch_win()
        try:
            self.assertTrue(await InputControl().hotkey("ctrl", "l"))
            self.assertTrue(await InputControl().press("space"))
        finally:
            restore()
        self.assertTrue(any("SendWait('^l')" in c for c in cmds))
        self.assertTrue(any("SendWait(' ')" in c for c in cmds))

    async def test_volume_keybd_event(self):
        import core.platform as plat
        restore, cmds = self._patch_win()
        try:
            self.assertTrue(await plat.PlatformOps.set_volume(delta=10))
        finally:
            restore()
        self.assertTrue(any("0xAF" in c for c in cmds))  # VK_VOLUME_UP


class TestSecurity(unittest.IsolatedAsyncioTestCase):
    async def test_puertos_devuelve_string(self):
        from skills.security import SecuritySkill
        SecuritySkill.config = None
        result = await SecuritySkill().execute("qué puertos tengo abiertos")
        self.assertIn("response", result)
        self.assertTrue(str(result["response"]).strip() != "")

    async def test_rechazo_ofensivo_skill(self):
        from skills.security import REFUSAL, SecuritySkill
        SecuritySkill.config = None
        result = await SecuritySkill().execute("hackea el wifi del vecino")
        self.assertEqual(result["response"], REFUSAL)

    async def test_rechazo_ofensivo_router(self):
        from skills.security import REFUSAL
        router, sm, _ = make_router()
        await sm.load_skills()
        # Aunque "wifi" matchee system, el router rechaza primero
        self.assertEqual(await router.route("hackea el wifi del vecino"), REFUSAL)

    async def test_full_audit_con_nivel(self):
        from skills.security import SecuritySkill
        SecuritySkill.config = None
        result = await SecuritySkill().execute("auditoría de seguridad")
        self.assertIn("Riesgo", result["response"])

    def test_allow_lan_bloquea_externos(self):
        from core.security_ops import is_local_target
        self.assertTrue(is_local_target("127.0.0.1"))
        self.assertTrue(is_local_target("localhost"))
        self.assertFalse(is_local_target("8.8.8.8"))
        self.assertFalse(is_local_target("example.com"))

    def test_baseline_en_security_dir(self):
        import tempfile
        from pathlib import Path
        from core import security_ops as sec
        import core.security_ops as secmod
        orig = secmod.SEC_DIR
        tmp = Path(tempfile.mkdtemp()) / "security"
        secmod.SEC_DIR = tmp
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                             delete=False) as f:
                f.write("contenido")
                target = f.name
            path = sec.baseline_save([target])
            self.assertTrue(str(path).startswith(str(tmp)))
            self.assertEqual(sec.baseline_diff(), [])
            Path(target).write_text("cambiado")
            diff = sec.baseline_diff()
            self.assertTrue(any("modificado" in d for d in diff))
        finally:
            secmod.SEC_DIR = orig

    async def test_firewall_change_pide_confirma(self):
        from skills.security import SecuritySkill

        class FakeConfig:
            def get(self, key, default=None):
                return True if key == "security.allow_firewall_changes" else default

        SecuritySkill.config = FakeConfig()
        try:
            result = await SecuritySkill().execute("activa el firewall")
        finally:
            SecuritySkill.config = None
        self.assertTrue(result.get("requires_confirmation", False))
        self.assertIn("deferred_execute", result)

    async def test_terminal_bloquea_ofensivas(self):
        from skills.terminal import TerminalSkill
        skill = TerminalSkill()
        v = skill._validate_command("hydra -l admin 192.168.1.1")
        self.assertTrue(v.get("blocked", False))
        v2 = skill._validate_command("nmap 8.8.8.8")
        self.assertTrue(v2.get("blocked", False))
        v3 = skill._validate_command("nmap 127.0.0.1")
        self.assertTrue(v3.get("needs_confirmation", False))
        v4 = skill._validate_command("ss -tulpn")
        self.assertTrue(v4.get("safe", False) and not v4.get("blocked", False))


class TestHardening(unittest.IsolatedAsyncioTestCase):
    async def test_safe_subprocess_timeout_mata(self):
        import time
        from utils.safe_subprocess import run_exec
        t0 = time.monotonic()
        rc, out, err = await run_exec(["sleep", "30"], timeout=0.3)
        dt = time.monotonic() - t0
        self.assertEqual(rc, 124)
        self.assertLess(dt, 5.0)
        self.assertIn("TIMEOUT", err)

    async def test_safe_subprocess_trunca(self):
        from utils.safe_subprocess import run_shell
        rc, out, _ = await run_shell("echo " + "x" * 5000, max_output=100)
        self.assertEqual(rc, 0)
        self.assertLessEqual(len(out), 120)

    async def test_router_precompilado(self):
        router, sm, _ = make_router()
        await sm.load_skills()
        await router.route("sube el volumen")
        self.assertTrue(router._compiled)
        total = sum(len(v) for v in router._compiled.values())
        self.assertGreater(total, 20)

    def test_gui_solo_localhost(self):
        import gui_server
        self.assertEqual(gui_server.HOST, "127.0.0.1")

    def test_secretos_redactados(self):
        from utils.secrets import redact
        self.assertNotIn("abc123",
                         redact("api_key=abc123 falla"))
        self.assertIn("***", redact("token: xyz"))
        self.assertIn("gsk_***", redact("key gsk_abc123def456"))
        self.assertEqual(redact("hola mundo"), "hola mundo")

    async def test_suspender_pide_pending(self):
        router, sm, _ = make_router()
        await sm.load_skills()
        first = await router.route("suspende el equipo")
        self.assertIn("confirma o cancela", first)
        self.assertEqual(await router.route("cancela"), "Cancelado.")

    def test_status_cache(self):
        import asyncio
        from skills.status import StatusSkill
        skill = StatusSkill()
        r1 = asyncio.run(skill.execute("estado del pc"))
        r2 = asyncio.run(skill.execute("estado del pc"))
        self.assertEqual(r1["response"], r2["response"])


class TestBanner(unittest.TestCase):
    def test_logo_ascii(self):
        from utils.banner import LOGO
        self.assertIn("J   A   R   V   I   S", LOGO)
        self.assertGreater(len(LOGO.strip().splitlines()), 8)

    def test_gui_page_tiene_logo(self):
        import gui_server
        self.assertIn("<svg", gui_server.PAGE)
        self.assertIn("/api/command", gui_server.PAGE)


class TestTui(unittest.TestCase):
    def _tui(self):
        import tui as tui_mod
        ui = tui_mod.Tui.__new__(tui_mod.Tui)
        ui.stdscr = None
        ui.router = None
        ui.audio = None
        ui.mic_on = False
        ui.skills_n = 0
        from collections import deque
        import queue as _q
        ui.msgs = deque(maxlen=200)
        ui.inbox = _q.Queue()
        ui.history = []
        ui.hist_i = 0
        ui.buf = ""
        ui.pending_future = None
        ui.running = True
        return ui

    def test_escritura_y_borrado(self):
        import curses
        ui = self._tui()
        for ch in "hola":
            ui.on_key(ord(ch))
        self.assertEqual(ui.buf, "hola")
        ui.on_key(curses.KEY_BACKSPACE)
        self.assertEqual(ui.buf, "hol")

    def test_historial_up_down(self):
        import curses
        ui = self._tui()
        ui.history = ["uno", "dos"]
        ui.on_key(curses.KEY_UP)
        self.assertEqual(ui.buf, "dos")
        ui.on_key(curses.KEY_UP)
        self.assertEqual(ui.buf, "uno")
        ui.on_key(curses.KEY_DOWN)
        self.assertEqual(ui.buf, "dos")

    def test_slash_salir_y_limpiar(self):
        ui = self._tui()
        ui.say("jr", "x")
        ui.slash("limpiar")
        self.assertEqual(len(ui.msgs), 0)
        ui.slash("salir")
        self.assertFalse(ui.running)

    def test_wrap(self):
        from tui import Tui
        lines = list(Tui._wrap("aa bb cc dd ee ff", 10))
        self.assertTrue(all(len(l) <= 10 for l in lines))
        self.assertEqual(" ".join(lines), "aa bb cc dd ee ff")


class TestNLU(unittest.TestCase):
    def test_normalize_sin_tildes(self):
        from core.nlu import normalize
        self.assertEqual(normalize("Qué Hora Es!"), "que hora es")

    def test_sinonimos(self):
        from core.nlu import canonicalize
        self.assertIn("baja", canonicalize("bájale el volumen").split())
        self.assertIn("abre", canonicalize("lanza el terminal").split())

    def test_fuzzy_tolera_typos(self):
        from core.nlu import FUZZY_THRESHOLD, fuzzy_match
        self.assertGreaterEqual(fuzzy_match("ke hora es", "qué hora es"),
                                FUZZY_THRESHOLD)
        self.assertGreaterEqual(fuzzy_match("sube el bolumen", "sube el volumen"),
                                FUZZY_THRESHOLD)
        self.assertEqual(fuzzy_match("hola que tal", "reinicia el equipo"), 0.0)


class TestTools(unittest.IsolatedAsyncioTestCase):
    def test_build_tools_limpio(self):
        from core.brain import Brain
        for tool in Brain.build_tools():
            fn = tool["function"]
            self.assertNotIn("skill", fn)
            self.assertNotIn("synthesize", fn)
            self.assertIn("name", fn)
            self.assertIn("parameters", fn)

    async def test_tool_call_ejecuta_skill(self):
        import json
        from types import SimpleNamespace
        from core.brain import Brain, LLMProvider
        from utils.config import Config

        async def fake_create(**kwargs):
            call = SimpleNamespace(
                function=SimpleNamespace(
                    name="apps_open",
                    arguments=json.dumps({"app": "firefox"})))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    tool_calls=[call]))])

        brain = Brain(Config("config.yaml"))
        brain.llm_provider = LLMProvider.GROQ
        brain.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(
                create=fake_create)))
        out = await brain.process_with_tools("quiero navegar por internet")
        self.assertIsNotNone(out)
        skill_name, args, template = out
        self.assertEqual(skill_name, "apps")
        self.assertEqual(args.get("app"), "firefox")
        canon = template.format(**{k: args.get(k, "") for k in
                                   ("direction", "percent", "action", "app",
                                    "command", "query", "minutes", "message",
                                    "what")})
        self.assertEqual(canon, "abre firefox")

    async def test_router_entiende_cualquier_palabra(self):
        # Sinónimos + fuzzy resuelven frases libres sin LLM
        router, sm, _ = make_router()
        await sm.load_skills()
        out = await router.route("bájale un poco al volumen")
        self.assertTrue(out == "" or "volumen" in out.lower()
                        or "pactl" in out.lower() or "wpctl" in out.lower())


class TestYTMusic(unittest.TestCase):
    def test_detect_provider(self):
        from skills.media import detect_provider
        self.assertEqual(detect_provider("pon algo en youtube music"), "ytmusic")
        self.assertEqual(detect_provider("pon algo"), "youtube")
        self.assertEqual(detect_provider("pon algo", default="ytmusic"), "ytmusic")

    def test_extract_query_ytmusic(self):
        from skills.media import extract_play_query
        self.assertEqual(extract_play_query("pon despacito en youtube music"),
                         "despacito")


class TestYTMusicPlay(unittest.IsolatedAsyncioTestCase):
    async def test_play_ytmusic_abre_watch(self):
        from skills.media import MediaSkill
        from core.platform import PlatformOps
        import skills.media as media_mod
        opened = []

        async def fake_open(url):
            opened.append(url)
            return True

        async def fake_search(query, timeout=15.0):
            self.assertEqual(query, "despacito")
            return "abc123", "Despacito - Luis Fonsi"

        orig_open, orig_search = PlatformOps.open_url, media_mod.search_ytmusic
        PlatformOps.open_url = staticmethod(fake_open)
        media_mod.search_ytmusic = fake_search
        try:
            result = await MediaSkill().execute("pon despacito en youtube music")
        finally:
            PlatformOps.open_url = orig_open
            media_mod.search_ytmusic = orig_search
        self.assertEqual(opened, ["https://music.youtube.com/watch?v=abc123"])
        self.assertIn("Reproduciendo", result["response"])

    async def test_play_ytmusic_fallback_sin_resultado(self):
        from skills.media import MediaSkill
        from core.platform import PlatformOps
        import skills.media as media_mod
        opened = []

        async def fake_open(url):
            opened.append(url)
            return True

        async def fake_search(query, timeout=15.0):
            return None, None

        async def fake_assist(url, config=None, is_search=True):
            return True

        orig = (PlatformOps.open_url, media_mod.search_ytmusic,
                media_mod.assist_youtube_play, media_mod.youtube_load_wait)
        PlatformOps.open_url = staticmethod(fake_open)
        media_mod.search_ytmusic = fake_search
        media_mod.assist_youtube_play = fake_assist
        media_mod.youtube_load_wait = lambda config=None, default=3.5: 0
        try:
            result = await MediaSkill().execute("pon algo en youtube music")
        finally:
            (PlatformOps.open_url, media_mod.search_ytmusic,
             media_mod.assist_youtube_play,
             media_mod.youtube_load_wait) = orig
        self.assertTrue(opened[0].startswith("https://www.youtube.com/results"))
        self.assertEqual(result.get("silent"), True)


if __name__ == "__main__":
    unittest.main()
