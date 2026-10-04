#!/usr/bin/env bash
#
# Instala xdotool + xclip en ~/.local SIN sudo (apt download + dpkg-deb).
# Idempotente: si ya existen, no hace nada.
#
set -euo pipefail

PREFIX="$HOME/.local/xdotools"
BIN="$PREFIX/usr/bin/xdotool"

if [ -x "$BIN" ]; then
    echo "⚡ [jarvis] xdotool local ya existe."
else
    echo "⚡ [jarvis] Descargando xdotool + xclip (sin sudo) ..."
    WORK="$(mktemp -d)"
    trap 'rm -rf "$WORK"' EXIT
    ( cd "$WORK" && apt download xdotool libxdo3 xclip wtype )
    mkdir -p "$PREFIX"
    for deb in "$WORK"/xdotool_*.deb "$WORK"/libxdo3_*.deb "$WORK"/xclip_*.deb "$WORK"/wtype_*.deb; do
        dpkg-deb -x "$deb" "$PREFIX" 2>/dev/null
    done
    mkdir -p "$HOME/.local/bin"
    ln -sf "$PREFIX/usr/bin/xdotool" "$HOME/.local/bin/xdotool"
    ln -sf "$PREFIX/usr/bin/xclip" "$HOME/.local/bin/xclip"
    [ -x "$PREFIX/usr/bin/wtype" ] && ln -sf "$PREFIX/usr/bin/wtype" "$HOME/.local/bin/wtype"
    echo "⚡ [jarvis] xdotool + xclip en ~/.local."
fi

export LD_LIBRARY_PATH="$PREFIX/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
if "$BIN" --help >/dev/null 2>&1; then
    echo "⚡ [jarvis] xdotool OK."
else
    echo "⚠️  [jarvis] xdotool no arranca (falta libX11 del sistema)." >&2
    exit 1
fi
