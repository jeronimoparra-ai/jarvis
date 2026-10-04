#!/usr/bin/env python3
"""
Jarvis TUI — interfaz completa en la terminal (sin web).

    python tui.py   (o ./jarvis.sh, que la usa si hay TTY)

- Logo + estado arriba, conversación al centro, entrada abajo.
- Escribe órdenes o habla (si hay mic: el wake-word sigue activo).
- Comandos: /salir /limpiar /chat /tareas /ayuda. Historial con ↑↓.
- Los recordatorios aparecen solos con aviso sonoro.
"""

import asyncio
import curses
import logging
import queue
import sys
import threading
from collections import deque
from concurrent.futures import Future
from pathlib import Path

logger = logging.getLogger("jarvis.tui")

MINI_LOGO = [
    r"  .-========-.  ",
    r" (  .-=-=-.  ) ",
    r"  (| (JARV) |)  ",
    r" (  '-=-=-'  ) ",
    r"  '-========-'  ",
]


class Tui:
    def __init__(self, stdscr, router, audio, mic_on: bool,
                 skills_n: int):
        self.stdscr = stdscr
        self.router = router
        self.audio = audio
        self.mic_on = mic_on
        self.skills_n = skills_n
        self.msgs: deque = deque(maxlen=200)
        self.inbox: "queue.Queue[str]" = queue.Queue()
        self.history: list[str] = []
        self.hist_i = 0
        self.buf = ""
        self.pending_future: Future | None = None
        self.running = True

    # -- dibujo ------------------------------------------------------------
    def draw(self) -> None:
        s = self.stdscr
        s.erase()
        h, w = s.getmaxyx()
        use_color = curses.has_colors()
        c_cy = curses.color_pair(1) if use_color else 0
        c_dim = curses.color_pair(2) if use_color else 0
        c_me = curses.color_pair(3) if use_color else 0

        # Cabecera: logo + estado
        for i, line in enumerate(MINI_LOGO):
            if i + 1 >= h - 4:
                break
            s.addnstr(i, 2, line, w - 4, c_cy)
        mode = "chat" if self.router.chat_session.active else "tareas"
        mic = "mic sí" if self.mic_on else "mic no"
        status = f"JARVIS · modo {mode} · {mic} · {self.skills_n} skills"
        s.addnstr(len(MINI_LOGO), 2, status[:w - 4], c_dim)
        s.hline(len(MINI_LOGO) + 1, 0, curses.ACS_HLINE, w)

        # Conversación (área scroll)
        top = len(MINI_LOGO) + 2
        bottom = h - 3
        visible = list(self.msgs)[-(bottom - top):]
        row = top
        for who, text in visible:
            if row >= bottom:
                break
            prefix = "tú> " if who == "me" else "Jarvis> "
            color = c_me if who == "me" else (c_cy if who == "ev" else 0)
            for chunk in self._wrap(prefix + text, w - 4):
                if row >= bottom:
                    break
                s.addnstr(row, 2, chunk, w - 4, color)
                row += 1

        # Entrada
        s.hline(h - 3, 0, curses.ACS_HLINE, w)
        prompt = "jarvis> " + self.buf
        s.addnstr(h - 2, 0, prompt[-(w - 1):], w - 1)
        s.move(h - 2, min(len(prompt), w - 1))
        s.refresh()

    @staticmethod
    def _wrap(text: str, width: int):
        width = max(10, width)
        while len(text) > width:
            cut = text.rfind(" ", 0, width)
            cut = cut if cut > 0 else width
            yield text[:cut]
            text = text[cut:].lstrip()
        yield text

    def say(self, who: str, text: str) -> None:
        if text:
            self.msgs.append((who, text))

    # -- entrada -------------------------------------------------------------
    def on_key(self, ch: int) -> None:
        if ch in (curses.KEY_ENTER, 10, 13):
            line = self.buf.strip()
            self.buf = ""
            self.hist_i = 0
            if line:
                self.history.append(line)
                self.submit(line)
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            self.buf = self.buf[:-1]
        elif ch == curses.KEY_UP:
            if self.history:
                self.hist_i = min(self.hist_i + 1, len(self.history))
                self.buf = self.history[-self.hist_i]
        elif ch == curses.KEY_DOWN:
            if self.hist_i > 1:
                self.hist_i -= 1
                self.buf = self.history[-self.hist_i]
            else:
                self.hist_i = 0
                self.buf = ""
        elif ch == 21:  # Ctrl+U: limpiar línea
            self.buf = ""
        elif 32 <= ch <= 0x10FFFF:
            try:
                c = chr(ch)
                if c.isprintable():
                    self.buf += c
            except (ValueError, OverflowError):
                pass

    def submit(self, line: str) -> None:
        self.say("me", line)
        if line.startswith("/"):
            self.slash(line[1:].strip().lower())
            return
        if self.pending_future is not None and not self.pending_future.done():
            self.say("jr", "Espera, aún proceso lo anterior…")
            return
        fut = asyncio.run_coroutine_threadsafe(
            self._answer(line), _BG_LOOP)
        self.pending_future = fut
        fut.add_done_callback(self._deliver)

    def slash(self, cmd: str) -> None:
        if cmd in ("salir", "exit", "quit", "q"):
            self.running = False
        elif cmd == "limpiar":
            self.msgs.clear()
        elif cmd == "chat":
            self._quick("modo chat")
        elif cmd == "tareas":
            self._quick("modo tareas")
        else:
            self.say("jr", "Comandos: /salir /limpiar /chat /tareas")

    def _quick(self, text: str) -> None:
        fut = asyncio.run_coroutine_threadsafe(
            self._answer(text), _BG_LOOP)
        fut.add_done_callback(self._deliver)

    async def _answer(self, text: str) -> str:
        try:
            response = await self.router.route(text)
            if response and self.audio is not None:
                try:
                    await self.audio.speak(response)
                except Exception:
                    pass
            return response or ""
        except Exception as e:
            logger.exception("TUI route falló: %s", e)
            return "Error interno."

    def _deliver(self, fut: Future) -> None:
        try:
            response = fut.result()
        except Exception as e:
            response = f"Error: {e}"
        if response:
            self.inbox.put(("jr", response))
        if self.pending_future is fut:
            self.pending_future = None


_BG_LOOP: asyncio.AbstractEventLoop = None  # type: ignore[assignment]


def _start_bg_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop


def _build() -> dict:
    """Inicializa Jarvis (igual que main.py) y devuelve componentes."""
    from utils.config import Config
    from utils.logger import setup_logger
    from core.audio import AudioSystem
    from core.router import Router
    from core.brain import Brain
    from core.skill_manager import SkillManager
    from core.pending import PendingManager
    from core.audit import AuditLog
    from core.profiles import apply_profile_to_config

    setup_logger("jarvis", "jarvis.log")
    base_dir = Path(__file__).resolve().parent
    config = Config(str(base_dir / "config.yaml"))
    apply_profile_to_config(config, base_dir)
    pending = PendingManager(
        float(config.get("pending.timeout_seconds", 12)))
    audit = AuditLog(enabled=bool(config.get("audit.enabled", True)))
    skill_manager = SkillManager(config)
    brain = Brain(config)
    router = Router(skill_manager, brain, config,
                    pending=pending, audit=audit)

    async def _init():
        await skill_manager.load_skills()
        from skills.audit_skill import AuditSkill
        AuditSkill.audit = audit
        from skills.system import register_system_undo_handlers
        await register_system_undo_handlers(audit)
        for mod, attr, val in (
                ("skills.routines", "RoutinesSkill", "manager"),
                ("skills.media", "MediaSkill", None),
                ("skills.coding", "CodingSkill", None),
                ("skills.security", "SecuritySkill", None),
                ("skills.status", "StatusSkill", None),
                ("skills.chat", "ChatSkill", None)):
            try:
                m = __import__(mod, fromlist=["x"])
                cls = getattr(m, attr)
                if val == "manager":
                    cls.manager = skill_manager
                    cls.config = config
                elif attr == "ChatSkill":
                    cls.session = router.chat_session
                else:
                    cls.config = config
            except ImportError:
                pass
        audio = AudioSystem(skill_manager, brain, config, router)
        mic_on = await audio.initialize()
        await brain.initialize()
        # Recordatorios -> cola de la TUI (con voz si hay TTS)
        reminder = skill_manager.get_skill("reminder")
        if reminder is not None and hasattr(reminder, "set_announce_callback"):
            async def _announce(message: str) -> None:
                _TUI_INBOX.put(("ev", f"Recordatorio: {message}"))
                try:
                    await audio.speak(f"Recordatorio: {message}")
                except Exception:
                    pass
            reminder.set_announce_callback(_announce)
        return {"router": router, "audio": audio, "brain": brain,
                "skills_n": len(skill_manager.list_skills()),
                "mic_on": bool(mic_on and audio.simulation_mode is False)}

    return asyncio.run_coroutine_threadsafe(
        _init(), _BG_LOOP).result(timeout=120)


_TUI_INBOX: "queue.Queue" = queue.Queue()


def _curses_main(stdscr, parts: dict) -> None:
    curses.curs_set(1)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_BLUE, -1)
        curses.init_pair(3, curses.COLOR_WHITE, -1)
    tui = Tui(stdscr, parts["router"], parts["audio"],
              parts["mic_on"], parts["skills_n"])
    tui.say("jr", "En línea. Escribe una orden, /chat para conversar, /salir para irte.")
    if parts["mic_on"]:
        tui.say("jr", "Micrófono activo: también puedes decir Hey Jarvis.")
    while tui.running:
        # Anuncios (recordatorios)
        while True:
            try:
                who, text = _TUI_INBOX.get_nowait()
            except queue.Empty:
                break
            tui.say(who, text)
            try:
                curses.beep()
            except Exception:
                pass
        # Respuestas que llegaron
        while True:
            try:
                who, text = tui.inbox.get_nowait()
            except queue.Empty:
                break
            tui.say(who, text)
        tui.draw()
        try:
            ch = stdscr.getch()
        except Exception:
            ch = -1
        if ch != -1:
            if ch == 3:  # Ctrl+C
                break
            tui.on_key(ch)
        else:
            import time as _t
            _t.sleep(0.03)
    # Drena respuestas en vuelo (máx 3 s) para no perder la última
    import time as _td
    deadline = _td.monotonic() + 3
    while _td.monotonic() < deadline:
        drained = False
        for q in (tui.inbox, _TUI_INBOX):
            while True:
                try:
                    who, text = q.get_nowait()
                except queue.Empty:
                    break
                tui.say(who, text)
                drained = True
        tui.draw()
        pending = tui.pending_future
        if (pending is None or pending.done()) and not drained:
            break
        _td.sleep(0.05)


def main() -> None:
    global _BG_LOOP
    _BG_LOOP = _start_bg_loop()
    try:
        parts = _build()
    except Exception as e:
        print(f"No se pudo iniciar Jarvis: {e}")
        return
    try:
        curses.wrapper(_curses_main, parts)
    except KeyboardInterrupt:
        pass
    finally:
        async def _cleanup():
            try:
                await parts["audio"].cleanup()
            except Exception:
                pass
            try:
                await parts["brain"].cleanup()
            except Exception:
                pass
        try:
            asyncio.run_coroutine_threadsafe(
                _cleanup(), _BG_LOOP).result(timeout=15)
        except Exception:
            pass
        _BG_LOOP.call_soon_threadsafe(_BG_LOOP.stop)
    print("Jarvis: Hasta luego.")


if __name__ == "__main__":
    if not sys.stdout.isatty():
        print("La TUI necesita una terminal interactiva. Usa ./jarvis.sh (simulación) o ./jarvis.sh gui.")
    else:
        main()
