#!/usr/bin/env python3
"""
NLU liviana sin dependencias pesadas (idea de los matchers semánticos
de otros Jarvis, pero con stdlib: normalización + sinónimos + fuzzy).

- normalize(): minúsculas, sin tildes, sin puntuación, espacios simples.
- SYNONYMS: variantes de verbos/objetos -> forma canónica.
- fuzzy_score(a, b): 0..1 con difflib (tolerante a typos y STT ruidoso).
"""

import difflib
import re
import unicodedata

# Umbral: similitud para aceptar un match difuso como fuerte
FUZZY_THRESHOLD = 0.78

# verbo/objeto coloquial -> canónico (se aplica por palabras completas)
SYNONYMS = {
    # volumen
    "bajale": "baja", "subele": "sube", "bájale": "baja", "súbele": "sube",
    "bajalo": "baja", "subilo": "sube", "reducele": "baja",
    "volumen": "volumen", "sonido": "volumen", "audio": "volumen",
    "silencia": "silencio", "mutea": "silencio", "enmudece": "silencio",
    # apps
    "abre": "abre", "abri": "abre", "inicia": "abre", "ejecuta app": "abre",
    "lanza": "abre", "corre app": "abre",
    "cierra": "cierra", "mata": "cierra", "termina app": "cierra",
    # energía
    "apaga": "apaga", "apagala": "apaga", "apágalo": "apaga",
    "reinicia": "reinicia", "rebootea": "reinicia",
    "suspende": "suspende", "hiberna": "suspende", "duerme": "suspende",
    "bloquea": "bloquea", "bloqueala": "bloquea",
    # media
    "pon": "pon", "reproduce": "pon", "reproduceme": "pon", "toca": "pon",
    "pausa": "pausa", "pausalo": "pausa", "parala": "pausa", "deten": "pausa",
    "cancion": "canción", "tema": "canción", "musica": "música",
    # web
    "busca": "busca", "googlea": "busca", "averigua": "busca",
    # hora/fecha
    "hora": "hora", "horario": "hora",
    # infinitivos -> imperativo de la skill
    "abrir": "abre", "cerrar": "cierra", "apagar": "apaga",
    "escuchar": "escucha", "reproducir": "pon", "buscar": "busca",
    "decir": "di", "poner": "pon", "pausar": "pausa",
    # varios
    "por favor": "", "porfa": "", "oye": "", "eh": "",
    "quiero": "", "quisiera": "", "necesito": "", "me": "",
}

# Pronombres enclíticos: "lanzame" -> "lanza", "abreme" -> "abre"
_ENCLITICS = ("mela", "melo", "tela", "telo", "sela", "selo", "nosla",
              "noslo", "me", "te", "se", "lo", "la", "los", "las",
              "le", "les", "nos")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes, sin puntuación, espacios simples."""
    text = text.lower().strip()
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _stem_enclitic(word: str) -> str:
    """Quita pronombres enclíticos ('lanzame'->'lanza') si deja verbo conocido."""
    for suffix in sorted(_ENCLITICS, key=len, reverse=True):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            stem = word[:-len(suffix)]
            if stem in SYNONYMS or stem in ("abre", "cierra", "lanza",
                                            "pon", "baja", "sube"):
                return stem
    return word


def canonicalize(text: str) -> str:
    """Aplica sinónimos sobre texto ya normalizado."""
    words = normalize(text).split()
    out = []
    i = 0
    # Bigramas primero ("ejecuta app")
    while i < len(words):
        bigram = " ".join(words[i:i + 2])
        if bigram in SYNONYMS and SYNONYMS[bigram]:
            out.append(SYNONYMS[bigram])
            i += 2
            continue
        w = _stem_enclitic(words[i])
        out.append(SYNONYMS.get(w, w))
        i += 1
    return re.sub(r"\s+", " ", " ".join(o for o in out if o)).strip()


def fuzzy_score(a: str, b: str) -> float:
    """Similitud 0..1 (difflib, sin dependencias)."""
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def fuzzy_match(text: str, pattern: str,
                threshold: float = FUZZY_THRESHOLD) -> float:
    """
    1.0 si el patrón normalizado aparece contenido;
    ratio difuso si supera el umbral; 0.0 si no.
    Compara contra la frase y contra ventanas de palabras (para
    patrones cortos dentro de frases largas habladas).
    """
    t = canonicalize(text)
    p = canonicalize(pattern)
    if not p:
        return 0.0
    if p in t:
        return 1.0
    best = fuzzy_score(t, p)
    words = t.split()
    n = max(1, len(p.split()))
    for size in {n, n + 1}:
        for i in range(max(1, len(words) - size + 1)):
            window = " ".join(words[i:i + size])
            best = max(best, fuzzy_score(window, p))
    return best if best >= threshold else 0.0
