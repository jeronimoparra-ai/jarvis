#!/usr/bin/env bash
#
# JARVIS — comando maestro.
# Prepara el entorno (venv + dependencias + .env) y ejecuta el asistente.
#
#   ./jarvis.sh               → interfaz de terminal TUI (o simulación si no hay TTY)
#   ./jarvis.sh tui           → fuerza la interfaz de terminal
#   ./jarvis.sh gui           → interfaz web minimalista (http://127.0.0.1:8765)
#   ./jarvis.sh install       → integra como app de escritorio (menú + icono)
#   ./jarvis.sh install --autostart → además arranca la GUI al iniciar sesión
#   ./jarvis.sh warmup        → pre-descarga modelos de voz (evita esperas)
#   ./jarvis.sh test          → ejecuta la suite de tests
#   ./jarvis.sh setup         → solo prepara el entorno, sin arrancar
#
set -euo pipefail

cd "$(dirname "$0")"

# Herramientas locales sin sudo (portaudio, xdotool): visibles siempre
if [ -d "$HOME/.local/xdotools/usr/lib/x86_64-linux-gnu" ]; then
    export LD_LIBRARY_PATH="$HOME/.local/xdotools/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
fi
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

VENV="venv"
MARKER="$VENV/.jarvis_ok"

msg()  { echo "⚡ [jarvis] $*"; }
warn() { echo "⚠️  [jarvis] $*" >&2; }

need_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "❌ [jarvis] python3 no encontrado. Instálalo primero." >&2
        exit 1
    fi
}

setup_env() {
    need_python
    if [ ! -d "$VENV" ]; then
        msg "Creando entorno virtual en ./$VENV ..."
        python3 -m venv "$VENV"
    fi
    # Reinstala si requirements.txt cambió desde la última instalación
    if [ ! -f "$MARKER" ] || [ "requirements.txt" -nt "$MARKER" ]; then
        msg "Instalando dependencias esenciales (puede tardar la primera vez) ..."
        "$VENV/bin/pip" install --quiet --upgrade pip
        "$VENV/bin/pip" install --quiet -r requirements.txt
        # Opcionales (mic/wake): best-effort, nunca bloquean
        if [ -f "requirements-optional.txt" ]; then
            if "$VENV/bin/pip" install --quiet -r requirements-optional.txt 2>/dev/null; then
                msg "Opcionales instalados (micrófono + wake-word)."
            elif [ -f "scripts/install_portaudio_local.sh" ]; then
                warn "Sin portaudio del sistema. Intentando instalación local sin sudo ..."
                if PATH="$VENV/bin:$PATH" bash scripts/install_portaudio_local.sh 2>/dev/null \
                    && "$VENV/bin/pip" install --quiet -r requirements-optional.txt 2>/dev/null; then
                    msg "Opcionales instalados vía PortAudio local."
                else
                    warn "Opcionales no disponibles. Jarvis usará modo simulación."
                fi
            # UI tools locales (xdotool/xclip): best-effort, nunca bloquean
            if [ -f "scripts/install_uitools_local.sh" ]; then
                bash scripts/install_uitools_local.sh 2>/dev/null \
                    && msg "UI tools locales listos (xdotool/xclip)." \
                    || warn "Sin xdotool: cursor/play asistido no disponible."
            fi
            else
                warn "Opcionales no instalados. Jarvis usará modo simulación."
                warn "Para micrófono real: sudo apt install -y portaudio19-dev y re-ejecuta ./jarvis.sh"
            fi
        fi
        touch "$MARKER"
    fi
    if [ ! -f ".env" ] && [ -f ".env.example" ]; then
        cp .env.example .env
        warn "Se creó .env desde .env.example. Pon tu GROQ_API_KEY para el LLM en la nube (opcional)."
    fi
    msg "Entorno listo."
}

cmd="${1:-run}"
case "$cmd" in
    setup)
        setup_env
        ;;
    test)
        setup_env
        msg "Ejecutando tests ..."
        "$VENV/bin/python" -m unittest tests.test_basic -v
        ;;
    warmup)
        setup_env
        msg "Pre-descargando modelos de voz ..."
        "$VENV/bin/python" scripts/warmup.py
        ;;
    gui)
        setup_env
        msg "Iniciando Jarvis GUI en http://127.0.0.1:8765 (Ctrl+C para salir) ..."
        exec "$VENV/bin/python" gui_server.py
        ;;
    install)
        setup_env
        shift || true
        bash scripts/install_desktop.sh "$@"
        ;;
    tui)
        setup_env
        if [ -t 0 ]; then
            msg "Iniciando Jarvis TUI (Ctrl+C o /salir para salir) ..."
            exec "$VENV/bin/python" tui.py
        else
            warn "Sin TTY: uso modo simulación clásico."
            exec "$VENV/bin/python" main.py
        fi
        ;;
    run|"")
        setup_env
        if [ -t 0 ] && "$VENV/bin/python" -c "import curses" 2>/dev/null; then
            msg "Iniciando Jarvis TUI (Ctrl+C o /salir para salir) ..."
            exec "$VENV/bin/python" tui.py
        else
            msg "Iniciando Jarvis (Ctrl+C para salir) ..."
            exec "$VENV/bin/python" main.py
        fi
        ;;
    *)
        echo "Uso: ./jarvis.sh [run|tui|gui|install|warmup|setup|test]" >&2
        exit 1
        ;;
esac
