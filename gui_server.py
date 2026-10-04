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
<!-- Jarvis GUI minimalista -->
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Jarvis</title>
<style>
  :root { --bg:#05090f; --panel:#0c1622; --line:#1c344c; --cy:#35e0ff;
          --cy-dim:#1a7fa0; --tx:#d7f6ff; --dim:#6f96b3; }
  * { box-sizing:border-box; }
  body { margin:0; color:var(--tx);
         font-family:"DejaVu Sans",Verdana,sans-serif; height:100vh;
         display:flex; justify-content:center;
         background:radial-gradient(600px 300px at 50% -60px, #0d2036 0%, var(--bg) 70%); }
  .app { width:100%; max-width:620px; display:flex; flex-direction:column;
         height:100vh; padding:22px 18px 14px; }
  header { display:flex; flex-direction:column; align-items:center; gap:2px;
           padding-bottom:14px; }
  .logo { width:74px; height:74px; filter:drop-shadow(0 0 14px rgba(53,224,255,.45)); }
  .logo .spin { transform-origin:60px 60px; animation:spin 24s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .logo .core { animation:core 3s ease-in-out infinite; }
  @keyframes core { 50% { opacity:.55; } }
  header h1 { font-size:19px; letter-spacing:10px; margin:8px 0 0 10px; font-weight:normal; }
  header small { color:var(--dim); font-size:12px; letter-spacing:1px; }
  header small .on { color:var(--cy); }
  #chat { flex:1; overflow-y:auto; padding:16px 4px; display:flex;
          flex-direction:column; gap:10px; scrollbar-width:thin;
          scrollbar-color:var(--line) transparent; }
  .msg { max-width:82%; padding:10px 15px; border-radius:16px; font-size:14px;
         line-height:1.5; animation:pop .18s ease-out; }
  @keyframes pop { from { transform:translateY(5px); opacity:0; } }
  .me { align-self:flex-end; background:linear-gradient(135deg,#17557c,#0f3a56);
        border-bottom-right-radius:5px; }
  .jr { align-self:flex-start; background:var(--panel); border:1px solid var(--line);
        border-bottom-left-radius:5px; color:#c4e6f5; }
  .jr.ev { border-color:var(--cy-dim); box-shadow:0 0 10px rgba(53,224,255,.12); }
  .jr.think { color:var(--dim); font-style:italic; }
  .jr.think span { animation:blink 1s infinite; }
  @keyframes blink { 50% { opacity:.2; } }
  .chips { display:flex; gap:8px; flex-wrap:wrap; padding:10px 0 4px; justify-content:center; }
  .chips button { background:rgba(53,224,255,.06); color:var(--cy);
                  border:1px solid var(--line); border-radius:20px;
                  padding:7px 15px; font-size:12px; cursor:pointer; transition:.15s; }
  .chips button:hover { border-color:var(--cy); background:rgba(53,224,255,.12); }
  form { display:flex; gap:10px; padding-top:12px; }
  input { flex:1; background:var(--panel); border:1px solid var(--line); color:var(--tx);
          border-radius:24px; padding:13px 18px; font-size:14px; outline:none; transition:.15s; }
  input:focus { border-color:var(--cy); box-shadow:0 0 0 3px rgba(53,224,255,.12); }
  form button { background:var(--cy); color:#04121c; border:none; border-radius:50%;
                width:48px; height:48px; font-size:18px; cursor:pointer; flex-shrink:0;
                transition:.15s; box-shadow:0 0 16px rgba(53,224,255,.35); }
  form button:hover { transform:scale(1.06); }
  footer { text-align:center; color:var(--dim); font-size:11px; padding-top:10px;
           letter-spacing:.5px; }
</style>
</head>
<body>
<div class="app">
  <header>
    <svg class="logo" viewBox="0 0 120 120" aria-label="Jarvis">
      <circle cx="60" cy="60" r="52" fill="none" stroke="#35e0ff" stroke-width="3" opacity=".9"/>
      <g class="spin" stroke="#1a7fa0" stroke-width="5" stroke-linecap="round">
        <line x1="60" y1="16" x2="60" y2="24"/>
        <line x1="60" y1="96" x2="60" y2="104"/>
        <line x1="16" y1="60" x2="24" y2="60"/>
        <line x1="96" y1="60" x2="104" y2="60"/>
        <line x1="29" y1="29" x2="35" y2="35"/>
        <line x1="85" y1="85" x2="91" y2="91"/>
        <line x1="91" y1="29" x2="85" y2="35"/>
        <line x1="35" y1="85" x2="29" y2="91"/>
      </g>
      <circle cx="60" cy="60" r="30" fill="#06121d" stroke="#35e0ff" stroke-width="2.5"/>
      <path class="core" d="M60 42 L76 74 L44 74 Z" fill="none" stroke="#aef6ff"
            stroke-width="4" stroke-linejoin="round"/>
    </svg>
    <h1>JARVIS</h1>
    <small><span class="on">●</span> en línea · escribe o habla</small>
  </header>
  <div id="chat"></div>
  <div class="chips">
    <button data-q="qué hora es">Hora</button>
    <button data-q="modo fiesta">Fiesta</button>
    <button data-q="modo chat">Chat</button>
    <button data-q="estado del pc">Estado</button>
    <button data-q="qué puedes hacer?">Ayuda</button>
  </div>
  <form id="f"><input id="i" autocomplete="off" placeholder="Escríbele a Jarvis…"/><button title="Enviar">➤</button></form>
  <footer>modo tareas · modo chat · di "Hey Jarvis" con micrófono</footer>
</div>
<script>
const chat = document.getElementById('chat');
const input = document.getElementById('i');
function add(who, text, ev=false) {
  if (!text) return;
  const d = document.createElement('div');
  d.className = 'msg ' + who + (ev ? ' ev' : '');
  d.textContent = text;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}
function thinking() {
  const d = document.createElement('div');
  d.className = 'msg jr think';
  d.innerHTML = 'Jarvis está pensando<span>…</span>';
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}
async function send(text) {
  text = text.trim();
  if (!text) return;
  add('me', text);
  input.value = '';
  const t = thinking();
  try {
    const r = await fetch('/api/command', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text})});
    const j = await r.json();
    t.remove();
    if (j.response) add('jr', j.response);
  } catch (e) { t.remove(); add('jr', 'Error de conexión con Jarvis.'); }
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
    try:
        from skills.security import SecuritySkill
        SecuritySkill.config = config
    except ImportError:
        pass
    try:
        from skills.chat import ChatSkill
        ChatSkill.session = router.chat_session
    except ImportError:
        pass
    try:
        from skills.status import StatusSkill
        StatusSkill.config = config
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
    from utils.banner import print_banner
    print_banner(tagline=False)
    print(f"Interfaz: {url} (se intenta abrir sola)\nCtrl+C para salir.\n")
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
