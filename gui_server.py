#!/usr/bin/env python3
"""
Jarvis GUI — interfaz web minimalista (solo stdlib, sin dependencias).

    python gui_server.py   (o ./jarvis.sh gui)

Abre http://127.0.0.1:8765 en el navegador: chat + acciones rápidas.
Los recordatorios cumplidos llegan como eventos (polling /api/events).
"""

import asyncio
import concurrent.futures
import json
import logging
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from utils.config import Config
from utils.logger import setup_logger
from core.router import Router
from core.brain import Brain
from core.skill_manager import SkillManager
from core.pending import PendingManager
from core.audit import AuditLog
from core.profiles import apply_profile_to_config

logger = logging.getLogger("jarvis.gui")

HOST = "127.0.0.1"
PORT = 8765

PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Jarvis</title>
<style>
  :root { --bg:#070d16; --panel:#0d1826; --line:#1e3a52; --cy:#35e0ff;
          --tx:#d7f6ff; --dim:#7fa8c4; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--tx);
         font-family:"DejaVu Sans",Verdana,sans-serif; height:100vh;
         display:flex; justify-content:center; }
  .app { width:100%; max-width:640px; display:flex; flex-direction:column;
         height:100vh; padding:18px; }
  header { display:flex; align-items:center; gap:12px; padding-bottom:12px;
           border-bottom:1px solid var(--line); }
  .dot { width:16px; height:16px; border-radius:50%; background:var(--cy);
         box-shadow:0 0 12px var(--cy); animation:pulse 2s infinite; }
  @keyframes pulse { 50% { opacity:.45; } }
  header h1 { font-size:20px; letter-spacing:8px; margin:0; }
  header small { color:var(--dim); margin-left:auto; font-size:12px; }
  #chat { flex:1; overflow-y:auto; padding:14px 2px; display:flex;
          flex-direction:column; gap:10px; }
  .msg { max-width:85%; padding:10px 14px; border-radius:14px; font-size:14px;
         line-height:1.45; }
  .me { align-self:flex-end; background:#16405e; border-bottom-right-radius:4px; }
  .jr { align-self:flex-start; background:var(--panel); border:1px solid var(--line);
        border-bottom-left-radius:4px; }
  .jr.ev { border-color:var(--cy); }
  .chips { display:flex; gap:8px; flex-wrap:wrap; padding:8px 0; }
  .chips button { background:transparent; color:var(--cy); border:1px solid var(--cy);
                  border-radius:20px; padding:6px 14px; font-size:12px; cursor:pointer; }
  .chips button:hover { background:#12334d; }
  form { display:flex; gap:8px; padding-top:8px; border-top:1px solid var(--line); }
  input { flex:1; background:var(--panel); border:1px solid var(--line); color:var(--tx);
          border-radius:12px; padding:12px; font-size:14px; outline:none; }
  input:focus { border-color:var(--cy); }
  form button { background:var(--cy); color:#04121c; border:none; border-radius:12px;
                padding:0 22px; font-size:14px; font-weight:bold; cursor:pointer; }
</style>
</head>
<body>
<div class="app">
  <header><span class="dot"></span><h1>JARVIS</h1><small id="st">en línea</small></header>
  <div id="chat"></div>
  <div class="chips">
    <button data-q="qué hora es">🕐 Hora</button>
    <button data-q="pausa la música">⏸ Música</button>
    <button data-q="sube el volumen">🔊 Volumen</button>
    <button data-q="toma una captura">📸 Captura</button>
    <button data-q="qué puedes hacer?">✨ Ayuda</button>
  </div>
  <form id="f"><input id="i" autocomplete="off" placeholder="Escribe una orden… (Enter para enviar)"/><button>➤</button></form>
</div>
<script>
const chat = document.getElementById('chat');
const input = document.getElementById('i');
function add(who, text, ev=false) {
  if (!text) return;
  const d = document.createElement('div');
  d.className = 'msg ' + who + (ev ? ' ev' : '');
  d.textContent = (who === 'jr' ? (ev ? '⏰ ' : 'Jarvis: ') : '') + text;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}
async function send(text) {
  text = text.trim();
  if (!text) return;
  add('me', text);
  input.value = '';
  try {
    const r = await fetch('/api/command', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text})});
    const j = await r.json();
    if (j.response) add('jr', j.response);
  } catch (e) { add('jr', 'Error de conexión con Jarvis.'); }
}
document.getElementById('f').addEventListener('submit', e => { e.preventDefault(); send(input.value); });
document.querySelectorAll('.chips button').forEach(b =>
  b.addEventListener('click', () => send(b.dataset.q)));
setInterval(async () => {
  try {
    const r = await fetch('/api/events');
    const j = await r.json();
    (j.events || []).forEach(ev => add('jr', ev, true));
  } catch (e) {}
}, 3000);
add('jr', 'En línea. Escríbeme una orden o toca un acceso rápido.');
input.focus();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "JarvisGUI/0.1"

    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/events":
            with self.server.lock:
                events = list(self.server.events)
                self.server.events.clear()
            self._json({"events": events})
            return
        page = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/command":
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
            text = str(data.get("text", "")).strip()
        except Exception:
            self._json({"error": "bad request"}, 400)
            return
        if not text:
            self._json({"response": ""})
            return
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self.server.loop.call_soon_threadsafe(self.server.queue.put_nowait, (text, fut))
        try:
            response = fut.result(timeout=30)
        except Exception as e:
            logger.error("Comando GUI falló: %s", e)
            response = "Error al procesar la orden."
        self._json({"response": response})

    def log_message(self, *args) -> None:
        pass


async def dispatcher(server: ThreadingHTTPServer, router: Router,
                     speak=None) -> None:
    """Consume la cola de la GUI dentro del loop asyncio."""
    while True:
        text, fut = await server.queue.get()
        try:
            response = await router.route(text) or ""
            if response and speak is not None:
                await speak(response)
            if not fut.done():
                fut.set_result(response)
        except Exception as e:
            logger.exception("Error en dispatcher: %s", e)
            if not fut.done():
                fut.set_result("Error interno.")


async def amain() -> None:
    setup_logger("jarvis", "jarvis.log")
    base_dir = Path(__file__).resolve().parent
    config = Config(str(base_dir / "config.yaml"))

    apply_profile_to_config(config, base_dir)
    pending = PendingManager(
        timeout_seconds=float(config.get("pending.timeout_seconds", 12)))
    audit = AuditLog(enabled=bool(config.get("audit.enabled", True)))

    skill_manager = SkillManager(config)
    brain = Brain(config)
    router = Router(skill_manager, brain, config, pending=pending, audit=audit)
    await skill_manager.load_skills()
    await brain.initialize()

    from skills.audit_skill import AuditSkill
    AuditSkill.audit = audit
    from skills.system import register_system_undo_handlers
    await register_system_undo_handlers(audit)
    try:
        from skills.routines import RoutinesSkill
        RoutinesSkill.manager = skill_manager
        RoutinesSkill.config = config
    except ImportError:
        pass
    try:
        from skills.media import MediaSkill
        MediaSkill.config = config
    except ImportError:
        pass
    try:
        from skills.coding import CodingSkill
        CodingSkill.config = config
    except ImportError:
        pass

    # Recordatorios -> eventos para la GUI
    events: list[str] = []
    lock = threading.Lock()

    async def announce(message: str) -> None:
        with lock:
            events.append(message)
            print(f"DEBUG-EV appended, len={len(events)} listid={id(events)}", flush=True)

    reminder = skill_manager.get_skill("reminder")
    if reminder is not None and hasattr(reminder, "set_announce_callback"):
        reminder.set_announce_callback(announce)
        logger.info("Recordatorios conectados a la GUI.")

    try:
        from core.audio import AudioSystem
        audio = AudioSystem(skill_manager, brain, config, router)
        await audio.initialize()  # best-effort para TTS; simulación si no hay mic
        speak = audio.speak
    except Exception as e:
        logger.warning("Sin TTS en GUI (%s). Solo texto.", e)
        audio, speak = None, None

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.queue = asyncio.Queue()  # type: ignore[attr-defined]
    server.events = events  # type: ignore[attr-defined]
    server.lock = lock  # type: ignore[attr-defined]
    server.loop = asyncio.get_running_loop()  # type: ignore[attr-defined]

    loop_task = asyncio.get_running_loop().create_task(dispatcher(server, router, speak))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{HOST}:{PORT}"
    logger.info("Jarvis GUI en %s", url)
    print(f"\n=== JARVIS GUI ===\nAbre {url} en tu navegador (se intenta abrir solo).\nCtrl+C para salir.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        loop_task.cancel()
        server.shutdown()
        if audio is not None:
            await audio.cleanup()
        await brain.cleanup()


if __name__ == "__main__":
    asyncio.run(amain())
