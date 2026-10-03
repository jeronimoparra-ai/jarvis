#!/usr/bin/env python3
"""
Audio system for Jarvis - Handles wake word, STT, and TTS.

Pipeline:
1. Wake word detection (continuous, o modo simulación por teclado)
2. Cuando se detecta: graba comando hasta silencio
3. Transcribe con faster-whisper
4. Envía texto al router
5. Ejecuta skill
6. Responde breve con Piper (o log si no hay TTS)
"""

import asyncio
import logging
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)

# Lazy imports para dependencias de audio
try:
    import pyaudio
except ImportError:
    pyaudio = None  # type: ignore

from core.brain import Brain
from core.skill_manager import SkillManager

# Router se importa solo para type-checking (evita ciclo)
try:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from core.router import Router
except Exception:
    pass


class AudioSystem:
    """Handles all audio input/output operations."""

    def __init__(self, skill_manager: SkillManager, brain: Brain,
                 config=None, router=None):
        self.skill_manager = skill_manager
        self.brain = brain
        self.config = config
        self.router = router  # se inyecta desde main.py

        def _cfg(key: str, default: Any) -> Any:
            try:
                if self.config is not None and hasattr(self.config, "get"):
                    return self.config.get(key, default)
            except Exception:
                pass
            return default

        self.sample_rate: int = int(_cfg("audio.sample_rate", 16000))
        self.chunk_size: int = int(_cfg("audio.chunk_size", 1024))
        self.silence_threshold: int = int(_cfg("audio.silence_threshold", 500))
        self.stt_language: str = str(_cfg("stt.language", "es"))
        self.stt_model_size: str = str(_cfg("stt.model_size", "small"))
        self.stt_device: str = str(_cfg("stt.device", "cpu"))
        self.tts_voice: str = str(_cfg("tts.voice", "es_ES-carlfm-x_low"))
        self.wake_engine_name: str = str(_cfg("wake_word.engine", "openwakeword")).lower()
        self.wake_model: str = str(_cfg("wake_word.model", "hey_jarvis"))

        self.audio: Optional[Any] = None
        self.stream: Optional[Any] = None
        self.wake_word_engine: Optional[Any] = None
        self.stt_model: Optional[Any] = None
        self.simulation_mode: bool = False
        self.is_listening: bool = False

        # TTS en proceso (rápido): voz piper precargada una sola vez
        self._piper_voice: Optional[Any] = None
        self._piper_failed: bool = False
        self._piper_lock = asyncio.Lock()
        self.voices_dir = Path.home() / ".local" / "share" / "jarvis" / "voices"

    # ---------- inicialización ----------

    async def initialize(self) -> bool:
        """Inicializa audio. Devuelve False si hay que usar simulación."""
        if pyaudio is None:
            logger.warning("pyaudio no instalado. Se usará modo simulación (teclado).")
            self.simulation_mode = True
            return False
        try:
            self.audio = pyaudio.PyAudio()
            if self.wake_engine_name == "openwakeword":
                await self._init_openwakeword()
            elif self.wake_engine_name == "vosk":
                await self._init_vosk()
            else:
                logger.warning("Motor wake-word '%s' no reconocido. Trigger manual.",
                               self.wake_engine_name)
            logger.info("Sistema de audio inicializado correctamente.")
            return True
        except Exception as e:
            logger.error("Fallo al inicializar audio (%s). Modo simulación.", e)
            self.simulation_mode = True
            self.audio = None
            return False

    async def _init_openwakeword(self):
        try:
            from openwakeword.model import Model as OWWModel  # type: ignore
            # No descargamos modelos aquí; se activan bajo demanda.
            # Si el paquete existe, marcamos motor disponible.
            self.wake_word_engine = "openwakeword"
            logger.info("OpenWakeWord disponible (modelo: %s).", self.wake_model)
        except ImportError:
            logger.warning("openwakeword no instalado. Trigger manual.")
            self.wake_word_engine = None
        except Exception as e:
            logger.warning("No se pudo iniciar openWakeWord: %s", e)
            self.wake_word_engine = None

    async def _init_vosk(self):
        try:
            from vosk import Model, KaldiRecognizer  # type: ignore
            self.wake_word_engine = "vosk"
            logger.info("Vosk disponible.")
        except ImportError:
            logger.warning("vosk no instalado. Trigger manual.")
            self.wake_word_engine = None
        except Exception as e:
            logger.warning("No se pudo iniciar Vosk: %s", e)
            self.wake_word_engine = None

    # ---------- bucle principal ----------

    async def listen_for_wake_word(self):
        """Bucle principal: wake-word real o simulación por teclado."""
        if self.simulation_mode or self.audio is None:
            await self._simulation_loop()
            return
        # Sin motor wake-word real cableado al mic: degradar a simulación
        # con aviso claro (evita quedarse en un sleep infinito mudo).
        if self.wake_word_engine is None:
            logger.warning("Sin motor wake-word operativo. Paso a modo simulación.")
            await self._simulation_loop()
            return
        try:
            await self._mic_loop()
        except Exception as e:
            logger.error("Error en bucle de micrófono (%s). Paso a simulación.", e)
            await self._simulation_loop()

    async def _simulation_loop(self):
        """Modo demo: lee comandos del teclado en vez del micrófono."""
        self.is_listening = True
        print("\n=== JARVIS modo simulación (sin micrófono) ===")
        print("Escribe un comando como si lo hubieras dicho.")
        print("Ejemplos: 'sube el volumen' | 'abre firefox' | 'ejecuta ls' | 'busca linux'")
        print("Escribe 'salir' para terminar.\n")
        logger.info("Simulación activa. Esperando entrada por teclado...")
        while True:
            try:
                line: str = await asyncio.to_thread(
                    input, "jarvis> "
                )
            except (EOFError, KeyboardInterrupt):
                print()
                break
            text = line.strip()
            if not text:
                continue
            if text.lower() in ("salir", "exit", "quit", "apagate"):
                print("Jarvis: Hasta luego.")
                break
            # Permite "hey jarvis, sube el volumen"
            text = self._strip_wake_word(text)
            if not text:
                continue
            response = await self.process_command(text)
            if response:
                print(f"Jarvis: {response}")
                await self.speak(response)
            # respuesta vacía = ejecución silenciosa exitosa

    def _strip_wake_word(self, text: str) -> str:
        low = text.lower().strip()
        for ww in ("hey jarvis", "oye jarvis", "ok jarvis", "jarvis"):
            if low.startswith(ww):
                return text[len(ww):].strip(" ,:")
        return text

    async def _mic_loop(self):
        """Bucle de micrófono: graba → transcribe → enruta → responde."""
        assert self.audio is not None
        self.is_listening = True
        logger.info("Escuchando (mic). Di el wake word '%s'...", self.wake_model)
        # Implementación pragmática: grabamos fragmentos y si hay voz,
        # los tratamos como comando (trigger por energía de voz).
        # El wake-word neuronal puro requiere modelos descargados; se
        # deja el hook _wake_detected() para enchufarlo sin cambiar el loop.
        stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
        )
        self.stream = stream
        try:
            while True:
                chunk = await asyncio.to_thread(
                    stream.read, self.chunk_size, False
                )
                if self._is_loud(chunk):
                    logger.info("Voz detectada, grabando comando...")
                    audio_data = await self.record_command(stream)
                    text = await self.transcribe(audio_data)
                    if not text:
                        continue
                    logger.info("Transcrito: %s", text)
                    response = await self.process_command(text)
                    if response:
                        await self.speak(response)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            self.stream = None

    # ---------- grabación / STT / TTS ----------

    def _rms(self, chunk: bytes) -> float:
        if not chunk:
            return 0.0
        n = len(chunk) // 2
        if n == 0:
            return 0.0
        fmt = "<" + "h" * n
        try:
            samples = struct.unpack(fmt, chunk[: n * 2])
        except struct.error:
            return 0.0
        return (sum(s * s for s in samples) / n) ** 0.5

    def _is_loud(self, chunk: bytes) -> bool:
        return self._rms(chunk) > self.silence_threshold

    async def record_command(self, stream=None) -> bytes:
        """Graba del mic hasta ~1.5 s de silencio. Sin mic → b''."""
        if pyaudio is None or self.audio is None:
            return b""
        own_stream = False
        if stream is None:
            try:
                stream = self.audio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self.sample_rate,
                    input=True,
                    frames_per_buffer=self.chunk_size,
                )
                own_stream = True
            except Exception as e:
                logger.error("No se pudo abrir el micrófono: %s", e)
                return b""
        frames: list[bytes] = []
        silent_chunks = 0
        max_silent = int(self.sample_rate / self.chunk_size * 1.5)
        max_total = int(self.sample_rate / self.chunk_size * 15)  # 15 s tope
        try:
            for _ in range(max_total):
                chunk = await asyncio.to_thread(stream.read, self.chunk_size, False)
                frames.append(chunk)
                if self._is_loud(chunk):
                    silent_chunks = 0
                else:
                    silent_chunks += 1
                if len(frames) > 10 and silent_chunks >= max_silent:
                    break
        except Exception as e:
            logger.error("Error grabando: %s", e)
        finally:
            if own_stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
        return b"".join(frames)

    async def _load_stt_model(self):
        if self.stt_model is not None:
            return
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError:
            logger.warning("faster-whisper no instalado. STT no disponible.")
            return
        try:
            self.stt_model = await asyncio.to_thread(
                WhisperModel, self.stt_model_size, self.stt_device
            )
            logger.info("Modelo STT cargado: %s (%s)", self.stt_model_size, self.stt_device)
        except Exception as e:
            logger.error("No se pudo cargar el modelo STT: %s", e)
            self.stt_model = None

    async def transcribe(self, audio_data: bytes) -> str:
        if not audio_data:
            return ""
        await self._load_stt_model()
        if self.stt_model is None:
            return ""
        try:
            # faster-whisper acepta fichero o array numpy; escribimos WAV temporal.
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                tmp = f.name
            try:
                with wave.open(tmp, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(self.sample_rate)
                    wf.writeframes(audio_data)
                def _transcribe():
                    try:
                        # vad_filter: ignora silencios (más rápido y preciso)
                        return self.stt_model.transcribe(
                            tmp, self.stt_language, vad_filter=True,
                            vad_parameters={"min_silence_duration_ms": 500})
                    except TypeError:
                        # faster-whisper antiguo sin vad_filter
                        return self.stt_model.transcribe(tmp, self.stt_language)
                segments, _ = await asyncio.to_thread(_transcribe)
                text = " ".join(s.text for s in segments)
                return text.strip()
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception as e:
            logger.error("Error STT: %s", e)
            return ""

    def _piper_voice_name(self) -> str:
        """Nombre de voz piper (config o default)."""
        try:
            configured = self.config.get("tts.voice", "") if self.config else ""
        except Exception:
            configured = ""
        if configured and configured.endswith(".onnx"):
            return configured
        if configured and "-" in configured and configured.count("-") >= 2:
            return configured  # p.ej. es_ES-davefx-medium
        return "es_ES-davefx-medium"

    def _ensure_piper_voice(self):
        """Descarga (una vez) y carga la voz en proceso. Devuelve voz o None."""
        if self._piper_voice is not None:
            return self._piper_voice
        if self._piper_failed:
            return None
        try:
            from piper import PiperVoice  # type: ignore
        except ImportError:
            self._piper_failed = True
            return None
        import sys
        name = self._piper_voice_name()
        try:
            if name.endswith(".onnx") and os.path.exists(name):
                model = name
            else:
                self.voices_dir.mkdir(parents=True, exist_ok=True)
                found = sorted(self.voices_dir.rglob("*.onnx"))
                if not found:
                    logger.info("Descargando voz Piper '%s' (una sola vez, ~60 MB)...", name)
                    subprocess.run(
                        [sys.executable or "python3", "-m", "piper.download_voices",
                         name, "--download-dir", str(self.voices_dir)],
                        check=True, capture_output=True, timeout=600)
                    found = sorted(self.voices_dir.rglob("*.onnx"))
                if not found:
                    raise RuntimeError("voz no encontrada tras descargar")
                # Prefiere la voz pedida si existe
                model = next((str(p) for p in found if name in str(p)), str(found[0]))
            self._piper_voice = PiperVoice.load(model)
            logger.info("Voz Piper en proceso lista: %s", model)
            return self._piper_voice
        except Exception as e:
            logger.warning("TTS en proceso no disponible (%s). Uso CLI/texto.", e)
            self._piper_failed = True
            return None

    async def _piper_synth(self, text: str) -> Optional[bytes]:
        """Sintetiza a WAV en proceso (rápido). None si no se puede."""
        def _work() -> Optional[bytes]:
            import io
            voice = self._ensure_piper_voice()
            if voice is None:
                return None
            chunks = list(voice.synthesize(text))
            if not chunks:
                return None
            rate = getattr(chunks[0], "sample_rate", 22050)
            width = getattr(chunks[0], "sample_width", 2)
            channels = getattr(chunks[0], "sample_channels", 1)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(width)
                wf.setframerate(rate)
                for c in chunks:
                    data = getattr(c, "audio_int16_bytes", b"")
                    if data:
                        wf.writeframes(data)
            return buf.getvalue()
        try:
            return await asyncio.to_thread(_work)
        except Exception as e:
            logger.debug("Síntesis piper falló: %s", e)
            return None

    async def _play_wav_bytes(self, wav_data: bytes) -> bool:
        """Reproduce WAV en memoria. True si sonó."""
        player = shutil.which("aplay") or shutil.which("paplay") or shutil.which("ffplay")
        if player is None:
            return False
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(wav_data)
            tmp = f.name
        try:
            args = [player, tmp]
            if player.endswith("ffplay"):
                args = [player, "-nodisp", "-autoexit", "-loglevel", "quiet", tmp]
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    async def speak(self, text: str):
        if not text or not text.strip():
            return
        # Siempre visible en log/consola aunque no haya TTS.
        logger.info("[Jarvis dice] %s", text)
        # Vía rápida: síntesis en proceso (voz precargada, sin re-spawn)
        wav_data = await self._piper_synth(text)
        if wav_data and await self._play_wav_bytes(wav_data):
            return
        # Fallback: CLI de piper
        piper_bin = shutil.which("piper")
        if piper_bin is None:
            return
        player = shutil.which("aplay") or shutil.which("paplay") or shutil.which("ffplay")
        if player is None:
            return
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            tmp = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                piper_bin, "--model", self.tts_voice,
                "--output_file", tmp,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate(text.encode("utf-8"))
            if proc.returncode != 0:
                return
            if player.endswith("ffplay"):
                await asyncio.create_subprocess_exec(
                    player, "-nodisp", "-autoexit", "-loglevel", "quiet", tmp,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
            else:
                await asyncio.create_subprocess_exec(
                    player, tmp,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
        except Exception as e:
            logger.warning("TTS falló (%s). Solo texto.", e)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    async def process_command(self, text: str) -> str:
        if self.router is None:
            logger.error("Router no inyectado en AudioSystem.")
            return await self.brain.process_with_llm(text)
        response = await self.router.route(text)
        if response is not None:
            return response
        return await self.brain.process_with_llm(text)

    async def cleanup(self):
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.audio is not None:
            try:
                self.audio.terminate()
            except Exception:
                pass
            self.audio = None
        logger.info("Sistema de audio liberado.")
