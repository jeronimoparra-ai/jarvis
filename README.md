<p align="center">
  <img src="assets/banner.svg" alt="Jarvis — asistente de voz para Linux" width="800"/>
</p>

<p align="center"><strong>Asistente de voz para Linux, orientado a tareas.</strong><br/>
Escucha · Transcribe · Ejecuta · Responde breve o en silencio.</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+"/>
  <img src="https://img.shields.io/badge/platform-linux-FCC624?style=flat-square&logo=linux&logoColor=black" alt="Linux"/>
  <img src="https://img.shields.io/badge/STT-faster--whisper-7C3AED?style=flat-square" alt="faster-whisper"/>
  <img src="https://img.shields.io/badge/TTS-piper-0E7490?style=flat-square" alt="Piper"/>
  <img src="https://img.shields.io/badge/LLM-groq%20%7C%20ollama-FF6B35?style=flat-square" alt="Groq / Ollama"/>
  <img src="https://img.shields.io/badge/license-MIT-22C55E?style=flat-square" alt="MIT"/>
</p>

## ⚡ Comando maestro

Un solo comando lo hace todo — crea el venv, instala dependencias, genera el `.env` y arranca:

```bash
git clone https://github.com/jeronimoparra-ai/jarvis.git
cd jarvis
./jarvis.sh
```

| Comando | Qué hace |
|---|---|
| `./jarvis.sh` | Prepara el entorno y **arranca Jarvis** (terminal) |
| `./jarvis.sh gui` | **Interfaz web minimalista** en http://127.0.0.1:8765 (chat + accesos rápidos + avisos de temporizadores) |
| `./jarvis.sh test` | Prepara el entorno y **ejecuta los tests** |
| `./jarvis.sh setup` | **Solo prepara** el entorno, sin arrancar |

> Si los opcionales (micrófono/wake-word) no se pueden instalar por falta de `portaudio`, el script avisa y sigue: Jarvis arranca en modo simulación por teclado. Para micrófono real: `sudo apt install -y portaudio19-dev` y re-ejecuta `./jarvis.sh`.

¿Prefieres el control manual? Sigue a [📦 Instalación](#-instalación).

---

## ✨ ¿Qué es Jarvis?

Jarvis es un asistente de voz **task-oriented** (no es un chatbot): recibe una orden hablada, detecta la intención con reglas deterministas y **ejecuta la acción** — subir el volumen, abrir una app, correr un comando o buscar en la web. Solo usa LLM (Groq u Ollama) como *fallback* cuando ningún patrón coincide, y responde en **máximo una frase** (o en silencio si todo salió bien).

```
🎙️ voz → 🔎 wake word → 📝 STT (faster-whisper) → 🧭 Router (reglas)
                                                        ├─ match fuerte → ⚡ Skill
                                                        └─ sin match → 🧠 Brain (Groq/Ollama/mock) → ⚡ Skill
                                                                                            → 🔊 Piper (o texto)
```

## 🚀 Características

| | |
|---|---|
| 🎯 **Reglas primero** | Router determinista con puntuación (regex, wildcards, frases, keywords). El LLM solo entra si el match es débil. |
| 🧩 **Skills modulares** | Cada habilidad es un archivo en `skills/`. Agregar una toma minutos. |
| 🔇 **Silencio ante el éxito** | Las acciones correctas no hablan; solo confirman lo riesgoso o lo que pide respuesta. |
| 🛡️ **Seguro por diseño** | Whitelist de comandos, confirmación con *“confirma”* y bloqueo absoluto de destructivos. |
| 💻 **Funciona sin micrófono** | Modo simulación por teclado si no hay `pyaudio`. Sin API key → modo offline con heurística. |
| ⚡ **Async de punta a punta** | `asyncio` en audio, STT, TTS, LLM y skills. |

## 📦 Instalación (manual, alternativa al comando maestro)

### 1. Requisitos del sistema (Ubuntu/Debian)

```bash
# Herramientas de audio y control del sistema
sudo apt update
sudo apt install -y portaudio19-dev python3-venv alsa-utils \
  pulseaudio-utils brightnessctl wmctrl playerctl \
  gnome-screenshot libnotify-bin
```

> **¿Sin sudo?** No pasa nada: `./jarvis.sh` instala PortAudio automáticamente en `~/.local/portaudio` (vía `scripts/install_portaudio_local.sh`) y compila `pyaudio` contra él. Sin micrófono, Jarvis arranca igual en **modo simulación por teclado**.

### 2. Entorno Python e instalación

```bash
git clone https://github.com/jeronimoparra-ai/jarvis.git
cd jarvis
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Opcionales (mic + wake-word, puede fallar sin portaudio: es normal):
pip install -r requirements-optional.txt || echo "modo simulación"
```

### 3. Configuración (opcional pero recomendada)

```bash
cp .env.example .env
# Edita .env y pon tu clave:
# GROQ_API_KEY=gsk_...
```

| Variable | Qué hace | Si la omites |
|---|---|---|
| `GROQ_API_KEY` | LLM rápido en la nube (fallback) | Usa Ollama local, luego modo offline |
| `LLM_PROVIDER` | `groq` u `ollama` | `groq` |
| `WAKE_WORD_ENGINE` | `openwakeword` o `vosk` | `openwakeword` |
| `STT_MODEL_SIZE` | `tiny`, `base`, `small`, `medium`, `large` | `small` |

El resto vive en `config.yaml` (dispositivos de audio, voces, skills activas).

### 4. Extras opcionales

```bash
# Voz en español para Piper (TTS real en vez de solo texto)
# Descarga una voz es_ES desde https://huggingface.co/rhasspy/piper-voices
# y apunta a ella en config.yaml → tts.voice

# Ollama local (LLM sin nube)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3
```

## ▶️ Uso

```bash
source venv/bin/activate
python main.py
```

Verás el modo simulación (o el mic si hay `pyaudio` + motor wake-word):

```
=== JARVIS modo simulación (sin micrófono) ===
jarvis> sube el volumen      # → silencio (hecho)
jarvis> ejecuta pwd           # → Jarvis: /home/usuario/jarvis
jarvis> qué es linux         # → Jarvis: resumen de Wikipedia + abre el navegador
jarvis> apaga el equipo      # → Jarvis: Vas a apagar el equipo. Di 'apaga, confirma'...
jarvis> salir                # → Jarvis: Hasta luego.
```

También acepta el wake word escrito: `hey jarvis, abre firefox`.

## 🧩 Skills incluidas

| Skill | Se activa con | Qué hace |
|---|---|---|
| 🔊 **system** (`skills/system.py`) | `volumen`, `brillo`, `apaga`, `reinicia`, `suspende`, `estado del sistema` | `pactl` / `brightnessctl` / `systemctl`. Energía **exige `confirma`**. |
| 🪟 **apps** (`skills/apps.py`) | `abre …`, `cierra …` | Lanza apps por alias (`navegador`, `terminal`, `vscode`…) o cierra con `pkill`. Enfoca la ventana vía `wmctrl`/`i3`/`sway` si existen. |
| ⌨️ **terminal** (`skills/terminal.py`) | `ejecuta …`, `corre …` | Whitelist directa (`ls`, `pwd`, `git`…), timeout 10 s, confirmación para lo sensible, bloqueo total de lo destructivo. |
| 🌐 **web** (`skills/web.py`) | `busca …`, `qué es …` | `busca X` abre DuckDuckGo en silencio; `qué es X` además **responde 1 frase de Wikipedia**. |
| 🕐 **clock** (`skills/clock.py`) | `qué hora es`, `qué fecha es` | Responde hora/fecha en español. |
| 🎵 **media** (`skills/media.py`) | `pausa`, `sigue`, `siguiente`, `qué suena` | Control vía `playerctl` (requiere instalarlo). |
| ⏰ **reminder** (`skills/reminder.py`) | `recuérdame en 5 minutos …`, `temporizador de 10 minutos` | Avisa con `notify-send` + voz/evento GUI al cumplirse (máx. 12 h). |
| 📸 **system** | `toma una captura`, `pantallazo` | Guarda en `~/Imágenes/jarvis-*.png` (requiere `gnome-screenshot`). |

### Crear tu propia skill

```python
# skills/saludo.py
from skills.base import Skill

class SaludoSkill(Skill):
    patterns = ["hola jarvis", "buenos días"]
    intent = "saludo"

    async def execute(self, text, intent=None):
        return {"response": "A su servicio, señor.", "silent": False}
```

1. Crea `skills/mi_skill.py` con `patterns` + `execute(text, intent)`.
2. Añádela a `skills.enabled` en `config.yaml`.
3. Devuelve `{"response": "...", "silent": False}` para hablar, o `"silent": True` para ejecución silenciosa. Usa `"requires_confirmation": True` si la acción es riesgosa.

## 🛡️ Modelo de seguridad

- **Confirmación explícita**: apagar, reiniciar, suspender, `rm`/`mv`/`chmod`/`kill`, redirecciones y comandos desconocidos **no se ejecutan** sin la palabra `confirma` en la misma orden (*“apaga, confirma”*).
- **Bloqueo absoluto** (ni con confirmación): `mkfs`, `dd`, borrado de `/`, fork-bombs.
- **Terminal acotada**: whitelist de comandos seguros, timeout de 10 s, salida truncada a 500 caracteres.

## ⚙️ Arquitectura

```
jarvis/
├── jarvis.sh             # ⚡ Comando maestro: setup + run + test
├── main.py               # Entrypoint: config → skills → audio → loop (Ctrl+C limpio)
├── config.yaml / .env    # Config externa (.env manda sobre el YAML)
├── requirements.txt / requirements-optional.txt  # Deps esenciales / mic+Wake
├── core/
│   ├── audio.py          # wake-word + grabación + STT + TTS + simulación por teclado
│   ├── router.py         # reglas con score → skill; débil/nulo → Brain
│   ├── brain.py          # Groq → Ollama → heurística offline + respuestas mock
│   └── skill_manager.py  # descubrimiento y carga de skills
├── skills/               # base.py + system, apps, terminal, web
├── utils/                # config.py (YAML + .env) y logger.py
├── tests/                # suite unittest (7 tests)
├── assets/               # logo.svg + banner.svg (identidad del proyecto)
└── LICENSE               # MIT
```

## ✅ Tests

```bash
source venv/bin/activate
python -m unittest tests.test_basic -v
```

Cubre: routing determinista, fallback LLM, terminal segura/bloqueada, confirmación de `rm` y de apagado, y extracción de queries web.

## ⚠️ Limitaciones conocidas

- Sin `pyaudio`/mic → modo simulación por teclado (totalmente funcional).
- El wake-word neuronal puro requiere descargar modelos de openWakeWord/Vosk; con mic pero sin modelos se usa trigger por energía de voz.
- `faster-whisper` descarga el modelo (`small` ≈ 500 MB) en el primer uso.
- Piper necesita su binario + voz; si falta, las respuestas salen como texto.
- Volumen/brillo reales requieren `pactl`/`brightnessctl`.

## 🖥️ Interfaz web

```bash
./jarvis.sh gui
```

Abre http://127.0.0.1:8765: chat minimalista oscuro, 5 accesos rápidos (hora, música, volumen, captura, ayuda) y avisos de temporizadores en vivo (polling cada 3 s). Implementada **solo con stdlib** (`http.server`), sin dependencias nuevas.

## 🗺️ Roadmap

- [x] Micrófono real sin sudo (PortAudio local + `pyaudio`)
- [x] Interfaz web minimalista
- [x] Skills de hora, música, temporizadores y capturas
- [ ] Descarga automática del modelo wake-word + VAD real (silero/webrtcvad)
- [ ] Confirmación por voz (sí/no) con estado de pending-action
- [ ] Skill domótica (MQTT) y calendario
- [ ] Empaquetado `.deb` / servicio `systemd --user`

## 📄 Licencia

MIT — ver [LICENSE](LICENSE).

<p align="center">Hecho con ⚡ para Linux. <strong>A su servicio, señor.</strong></p>
