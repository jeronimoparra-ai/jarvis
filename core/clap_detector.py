#!/usr/bin/env python3
"""
Detector de doble aplauso sobre el stream del micrófono.

Dos picos fuertes (flanco de subida sobre energy_threshold) separados
entre min_gap_ms y max_gap_ms disparan. Cooldown tras disparar.
Funciona igual en Linux y Windows: solo necesita muestras int16.

Uso: detector.feed(samples_16000hz) -> True al detectar el doble aplauso.
"""

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ClapConfig:
    enabled: bool = True
    energy_threshold: float = 2500.0
    min_gap_ms: int = 120
    max_gap_ms: int = 900
    cooldown_s: float = 3.0
    routine: str = "modo_fiesta"

    @classmethod
    def from_dict(cls, data: dict) -> "ClapConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            energy_threshold=float(data.get("energy_threshold", 2500)),
            min_gap_ms=int(data.get("min_gap_ms", 120)),
            max_gap_ms=int(data.get("max_gap_ms", 900)),
            cooldown_s=float(data.get("cooldown_s", 3)),
            routine=str(data.get("routine", "modo_fiesta")),
        )


class ClapDetector:
    """Detecta doble aplauso con máquina de estados mínima."""

    def __init__(self, config: ClapConfig):
        self.config = config
        self._was_loud = False
        self._first_onset: float | None = None
        self._last_fire = float("-inf")

    def reset(self) -> None:
        self._was_loud = False
        self._first_onset = None

    def feed(self, samples, now: float | None = None) -> bool:
        """
        Alimenta muestras int16 mono. True solo en el momento del
        segundo aplauso válido.
        """
        if not self.config.enabled:
            return False
        now = now if now is not None else time.monotonic()
        try:
            peak = max(abs(int(s)) for s in samples) if len(samples) else 0
        except (TypeError, ValueError):
            return False
        loud = peak >= self.config.energy_threshold

        fired = False
        if loud and not self._was_loud:
            # Flanco de subida = posible aplauso
            if (self._first_onset is not None
                    and now - self._last_fire >= self.config.cooldown_s):
                gap_ms = (now - self._first_onset) * 1000
                if self.config.min_gap_ms <= gap_ms <= self.config.max_gap_ms:
                    fired = True
                    self._last_fire = now
                    self._first_onset = None
                elif gap_ms > self.config.max_gap_ms:
                    self._first_onset = now  # reinicia ventana
                # si gap < min: rebote, se ignora
            elif self._first_onset is None:
                if now - self._last_fire >= self.config.cooldown_s:
                    self._first_onset = now
            elif (now - self._first_onset) * 1000 > self.config.max_gap_ms:
                self._first_onset = now
        self._was_loud = loud

        # Expira primer aplauso huérfano
        if (self._first_onset is not None
                and (now - self._first_onset) * 1000 > self.config.max_gap_ms):
            self._first_onset = None

        if fired:
            logger.info("Doble aplauso detectado -> rutina '%s'",
                        self.config.routine)
        return fired
