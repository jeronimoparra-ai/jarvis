#!/usr/bin/env python3
"""Pre-descarga modelos (STT faster-whisper + VAD Silero + voz Piper).

Evita esperas de cientos de MB en el primer uso por voz.
Uso: ./jarvis.sh warmup
"""
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    from faster_whisper import WhisperModel
    print("⚡ [jarvis] Descargando/cargando STT (small, ~500 MB, una vez)...")
    model = WhisperModel("small", device="cpu")

    # WAV de 1 s de silencio para forzar la descarga del VAD Silero (~2 MB)
    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
        tmp = f.name
    try:
        with wave.open(tmp, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00" * 32000)
        print("⚡ [jarvis] Verificando VAD...")
        list(model.transcribe(tmp, "es", vad_filter=True,
                              vad_parameters={"min_silence_duration_ms": 500})[0])
    finally:
        os.unlink(tmp)

    from utils.config import Config
    from core.audio import AudioSystem
    print("⚡ [jarvis] Verificando voz Piper...")
    import asyncio

    async def _voice():
        from core.audio import AudioSystem
        a = AudioSystem(None, None, Config("config.yaml"))
        voice = await asyncio.to_thread(a._ensure_piper_voice)
        return voice is not None

    ok = asyncio.run(_voice())
    print("⚡ [jarvis] Voz Piper:", "lista" if ok else "no disponible (se usará texto)")
    print("⚡ [jarvis] Warmup completo. Ya puedes hablarle sin esperas.")


if __name__ == "__main__":
    main()
