#!/usr/bin/env bash
#
# Instala PortAudio en ~/.local/portaudio SIN sudo (apt download + dpkg-deb)
# y compila pyaudio contra él. Idempotente: si ya existe, no hace nada.
#
set -euo pipefail

PREFIX="$HOME/.local/portaudio"
HEADER="$PREFIX/usr/include/portaudio.h"

if [ -f "$HEADER" ]; then
    echo "⚡ [jarvis] PortAudio local ya existe en $PREFIX"
else
    echo "⚡ [jarvis] Descargando PortAudio (sin sudo) ..."
    WORK="$(mktemp -d)"
    trap 'rm -rf "$WORK"' EXIT
    ( cd "$WORK" && apt download libportaudio2 portaudio19-dev )
    mkdir -p "$PREFIX"
    dpkg-deb -x "$WORK"/libportaudio2_*.deb "$PREFIX"
    dpkg-deb -x "$WORK"/portaudio19-dev_*.deb "$PREFIX"
    echo "⚡ [jarvis] PortAudio extraído en $PREFIX"
fi

echo "⚡ [jarvis] Compilando pyaudio ..."
LIBDIR="$PREFIX/usr/lib/x86_64-linux-gnu"
CFLAGS="-I$PREFIX/usr/include" \
LDFLAGS="-L$LIBDIR -Wl,-rpath,$LIBDIR" \
    pip install pyaudio
python -c "import pyaudio; print('⚡ [jarvis] pyaudio OK:', pyaudio.get_portaudio_version_text())"
