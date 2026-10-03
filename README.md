# Jarvis — Asistente de voz para Linux (task-oriented)

Asistente modular orientado a tareas: escucha, transcribe, enruta por reglas y
solo usa LLM como fallback. Respuestas breves; éxito = silencio.

## Flujo

```
teclado/mic → (wake) → STT faster-whisper → Router (reglas) → Skill
                                                └─ sin match → Brain (Groq/Ollama/mock)
```

## Instalación en Linux

```bash
cd jarvis
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Opcional micrófono real (sin esto hay modo simulación por teclado):
sudo apt install portaudio19-dev  # y reinstala pyaudio

# Configura tu clave (opcional pero recomendada):
cp .env.example .env   # edita GROQ_API_KEY
```

Sin `GROQ_API_KEY` ni Ollama local (`http://localhost:11434`), el Brain usa
heurística offline + respuestas mock. Nada crashea.

## Uso

```bash
source venv/bin/activate
python main.py
# modo simulación: escribe comandos. 'salir' termina. Ctrl+C cierra limpio.
```

Comandos de ejemplo:

- `sube el volumen` / `baja el volumen`
- `abre firefox` / `cierra firefox`
- `ejecuta pwd` (whitelist directa)
- `busca linux` (abre DuckDuckGo)
- `hola` (fallback LLM/mock)

## Seguridad: confirmaciones

Acciones de alto riesgo **no se ejecutan** sin la palabra `confirma`:

- `apaga el equipo` → pide `apaga, confirma`
- `reinicia` / `suspende` → igual
- Terminal: `rm`, `mv`, `chmod`, `kill`, encadenados (`;`, `&&`, `|`), comandos
  desconocidos → piden `..., confirma`
- Bloqueo absoluto (ni con confirmación): `mkfs`, `dd`, borrado de `/`, fork-bomb.

## Skills

| Skill (`skills/`) | Dispara con | Hace |
|---|---|---|
| `system.py` | `volumen`, `brillo`, `apaga`, `reinicia`, `suspende` | pactl / brightnessctl / systemctl (con confirmación) |
| `apps.py` | `abre`, `cierra` | lanza apps por alias o `pkill` para cerrar |
| `terminal.py` | `ejecuta`, `corre` | whitelist + confirmación + timeout 10 s |
| `web.py` | `busca`, `qué es` | abre búsqueda DuckDuckGo |

Nueva skill: crea `skills/mi_skill.py` con clase `Skill`, define `patterns`,
e impleméntala en `execute(text, intent) -> {"response": ..., "silent": ...}`.
Añádela a `skills.enabled` en `config.yaml`.

## Configuración

`config.yaml` + `.env` (`.env` manda sobre el YAML):

| Clave | Env override | Default |
|---|---|---|
| `llm.provider` | `LLM_PROVIDER` | `groq` |
| `llm.api_key` | `GROQ_API_KEY` | `YOUR_API_KEY` |
| `wake_word.engine` | `WAKE_WORD_ENGINE` | `openwakeword` |
| `stt.model_size` | `STT_MODEL_SIZE` | `small` |

## Tests

```bash
source venv/bin/activate
python -m unittest tests.test_basic -v
```

6 tests: router determinista, fallback LLM, terminal segura/bloqueada,
confirmación de `rm` y de apagado.

## Estado / limitaciones conocidas

- Sin micrófono/`pyaudio` → modo simulación por teclado (funcional).
- Wake-word neuronal real requiere modelos descargados; el loop de mic usa
  detección por energía de voz como trigger pragmático.
- STT `faster-whisper` descarga el modelo (`small` ≈ 500 MB) en el primer uso.
- TTS Piper requiere binario `piper` + voz; si falta, solo texto en consola.
- `pactl`/`brightnessctl` deben existir para volumen/brillo reales.
