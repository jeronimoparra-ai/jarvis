#!/usr/bin/env python3
"""Logo ASCII de Jarvis para la terminal."""

LOGO = r"""
              .--========--.
           _.'  .--------.  '._
         .'   .'  .----.  '.   '.
        /    /   /  /\  \   \    \
       |    |   |  ||  |   |    |
       |    |   |  ||  |   |    |
        \    \   \ \/ /   /    /
         '.   '.  '--'  .'   .'
           '._  '----'  _.'
              '--====--'

     J   A   R   V   I   S
     ─────────────────────
"""

TAGLINE = "Asistente de voz · Di 'Hey Jarvis' o escribe tu orden"


def print_banner(tagline: bool = True) -> None:
    """Imprime el logo (con color cian si la terminal lo soporta)."""
    import os
    import sys
    cyan = "\033[96m"
    dim = "\033[2m"
    reset = "\033[0m"
    use_color = sys.stdout.isatty() and os.getenv("NO_COLOR") is None
    art = LOGO
    if use_color:
        art = "".join(
            (cyan + line + reset) if line.strip() else line
            for line in LOGO.splitlines(keepends=True)
        )
    print(art)
    if tagline:
        line = TAGLINE
        print(f"{dim}{line}{reset}" if use_color else line)
