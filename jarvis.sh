#!/usr/bin/env bash
#
# JARVIS — comando maestro.
# Prepara el entorno (venv + dependencias + .env) y ejecuta el asistente.
#
#   ./jarvis.sh          → instala lo necesario y arranca Jarvis
#   ./jarvis.sh test     → ejecuta la suite de tests
#   ./jarvis.sh setup    → solo prepara el entorno, sin arrancar
#
set -euo pipefail

cd "$(dirname "$0")"

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
            else
                warn "Opcionales no instalados (falta portaudio u otro). Jarvis usará modo simulación."
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
    run|"")
        setup_env
        msg "Iniciando Jarvis (Ctrl+C para salir) ..."
        exec "$VENV/bin/python" main.py
        ;;
    *)
        echo "Uso: ./jarvis.sh [run|setup|test]" >&2
        exit 1
        ;;
esac
