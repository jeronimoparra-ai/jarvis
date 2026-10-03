#!/usr/bin/env bash
#
# Integra Jarvis como aplicación de escritorio (Linux):
#   - Icono en ~/.local/share/icons/jarvis.svg
#   - Lanzadores en ~/.local/share/applications (Jarvis terminal + Jarvis GUI)
#   - Opcional: autostart de la GUI al iniciar sesión (--autostart)
#
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
ICON_DIR="$HOME/.local/share/icons"
APPS_DIR="$HOME/.local/share/applications"
AUTO_DIR="$HOME/.config/autostart"

mkdir -p "$ICON_DIR" "$APPS_DIR"
cp -f assets/logo.svg "$ICON_DIR/jarvis.svg"

make_entry() { # $1=nombre $2=exec-args $3=terminal $4=comment
    cat > "$APPS_DIR/$1.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$2
Comment=$4
Icon=jarvis
Exec=$ROOT/jarvis.sh $3
Terminal=$5
Categories=Utility;Accessibility;
StartupNotify=false
EOF
}

make_entry "jarvis" "Jarvis" "" "Asistente de voz (terminal)" "true"
make_entry "jarvis-gui" "Jarvis GUI" "gui" "Asistente de voz (interfaz web)" "false"

update-desktop-database "$APPS_DIR" 2>/dev/null || true

if [ "${1:-}" = "--autostart" ]; then
    mkdir -p "$AUTO_DIR"
    cp -f "$APPS_DIR/jarvis-gui.desktop" "$AUTO_DIR/"
    echo "⚡ [jarvis] Autostart activado (GUI al iniciar sesión)."
fi

echo "⚡ [jarvis] Listo. Busca 'Jarvis' en el menú de aplicaciones."
