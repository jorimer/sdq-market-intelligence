"""BM25-lite sobre pasajes con procedencia — determinista, puro Python.

Okapi BM25 con parámetros estándar (k1=1.5, b=0.75). Tokenización en español-neutro:
minúsculas, sin acentos, sin stopwords cortas. No indexa nada que no venga con
``source`` (la regla §4 se cumple desde el índice, no solo desde el llamador).
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

from shared.knowledge.models import Passage

# Stopwords ES + algunos términos EN frecuentes en los docs bilingües. Lista corta a
# propósito: BM25 ya penaliza términos muy frecuentes vía IDF; esto solo quita el ruido.
_STOPWORDS = frozenset("""
a al algo alguna algunas alguno algunos ante antes como con contra cual cuando de del
desde donde dos el ella ellas ellos en entre era erais eran es esa esas ese eso esos
esta estas este esto estos ha hasta hay la las le les lo los mas más me mi mis mucho muy
no nos o os otra otras otro otros para pero poco por porque que se sea sean segun si sin
sobre solo son su sus tan te tiene tras un una uno unas unos y ya
the and for with that this from are was има not you your our its
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def tokenize(text: str) -> List[str]:
    """Tokeniza a español-neutro: minúsculas, sin acentos, sin stopwords, len≥2."""
    norm = _strip_accents(text.lower())
    return [t for t in _TOKEN_RE.findall(norm) if len(t) >= 2 and t not in _STOPWORDS]


class LexicalIndex:
    """Índice BM25 inmutable construido sobre una colección de :class:`Passage`."""

    K1 = 1.5
    B = 0.75

    def __init__(self, passages: Sequence[Passage]):
        # Solo pasajes con lineage: un pasaje sin ``source`` no entra al índice (§4).
        self._passages: List[Passage] = [p for p in passages if p.source and p.text]
        self._doc_tokens: List[List[str]] = [tokenize(p.text) for p in self._passages]
        self._doc_len: List[int] = [len(t) for t in self._doc_tokens]
        self._avgdl: float = (sum(self._doc_len) / len(self._doc_len)) if self._doc_len else 0.0
        # term frequency por doc + document frequency global.
        self._tf: List[Dict[str, int]] = []
        df: Dict[str, int] = {}
        for toks in self._doc_tokens:
            tf: Dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            self._tf.append(tf)
            for t in tf:
                df[t] = df.get(t, 0) + 1
        n = len(self._passages)
        # IDF de Okapi con suavizado (siempre > 0 para no dar scores negativos).
        self._idf: Dict[str, float] = {
            t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()
        }

    def __len__(self) -> int:
        return len(self._passages)

    def _score_doc(self, q_tokens: Sequence[str], i: int) -> float:
        if not self._avgdl:
            return 0.0
        tf = self._tf[i]
        dl = self._doc_len[i]
        score = 0.0
        for t in q_tokens:
            f = tf.get(t)
            if not f:
                continue
            idf = self._idf.get(t, 0.0)
            denom = f + self.K1 * (1 - self.B + self.B * dl / self._avgdl)
            score += idf * (f * (self.K1 + 1)) / denom
        return score

    def search(self, query: str, top_k: int = 5,
               min_score: float = 0.0) -> List[Tuple[Passage, float]]:
        """Los ``top_k`` pasajes con mayor score BM25 para *query* (score > ``min_score``).

        Vacío si nada supera el umbral — es una señal legítima de BRECHA para el
        orquestador (§4): "no tengo evidencia para esto", no un relleno."""
        q = tokenize(query)
        if not q or not self._passages:
            return []
        scored = [(self._passages[i], self._score_doc(q, i))
                  for i in range(len(self._passages))]
        scored = [(p, s) for p, s in scored if s > min_score]
        scored.sort(key=lambda ps: ps[1], reverse=True)
        return scored[:top_k]
