"""Gate: la prosa curada NO afirma procedencia — esa frase la genera el registro.

Lección del Hallazgo 7 (2026-07-22): el gate de citabilidad atrapa tablas y código en el
texto citable, pero no atrapa AFIRMACIONES VENCIDAS. El ``rationale`` del IAI declaró como
rúbrica cuatro variables ya reales durante semanas — envejeció solo, con cada conector
nuevo — mientras el prompt del IRC afirmaba "100% dato real" de un índice cuya transición
cae a rúbrica cuando el sync de Ember falla. Ninguna prosa que AFIRME procedencia puede
estar bien de forma estable, porque la procedencia es un estado por-corrida.

La separación que este gate hace cumplir:
- ``rationale`` (doctrina citable) → SOLO lo durable: qué mide, por qué pesa.
- Procedencia → la genera ``shared/registry/provenance.py`` del registro en vivo.

Si este test te falló: no "arregles" la frase — MUÉVELA. La afirmación de procedencia
sobra en la prosa curada porque la sección de Metodología ya la genera del estado real.
"""
import re
from pathlib import Path

import yaml  # type: ignore[import-untyped]  # sin stubs; mismo caso que corpus/__init__

from shared.knowledge.corpus import CORPUS_MANIFEST, _rationales_from_doctrine

_REPO = Path(__file__).resolve().parents[4]

# Vocabulario de ESTADO de procedencia. Prohibido en prosa curada: cualquiera de estas
# frases describe el estado de los datos de HOY, que mañana puede ser otro.
_PROVENANCE_VOCAB = re.compile(
    r"dato real|rúbrica|rubrica|fuente viva|se descontinu|hoy corre|"
    r"aún no|todav[ií]a no|mientras no (haya|se conecte)|sin fuente|100\s*%",
    re.IGNORECASE,
)

# Afirmaciones TOTALES de estado, prohibidas en los prompts de doctrina del cerebro.
# (Las instrucciones de LEER la procedencia del contexto — "respetas la procedencia",
# "cuánto se apoya en dato real vs rúbrica" — son válidas y no calzan estos patrones.)
_TOTAL_CLAIMS = re.compile(
    r"100\s*%\s*(dato\s*real|real|rúbrica)|no hay rúbrica|sin rúbrica que|"
    r"todo (es )?dato real|es 100\s*%",
    re.IGNORECASE,
)


def test_rationales_do_not_assert_provenance():
    """Ningún rationale citable afirma el estado de los datos."""
    offenders = []
    for src in CORPUS_MANIFEST:
        data = yaml.safe_load((_REPO / src.path).read_text(encoding="utf-8")) or {}
        for key, text in _rationales_from_doctrine(data):
            m = _PROVENANCE_VOCAB.search(text)
            if m:
                offenders.append(f"{src.path} :: {key} :: «…{m.group(0)}…»")
    assert not offenders, (
        "Rationale(s) con vocabulario de procedencia — esa frase la GENERA el registro "
        "(shared/registry/provenance.py), no se escribe a mano. Quita la afirmación del "
        "rationale (deja solo qué mide y por qué pesa):\n  " + "\n  ".join(offenders)
    )


def test_cerebro_doctrine_makes_no_total_provenance_claims():
    """Ninguna doctrina de eje del cerebro afirma que TODO el índice es real (o rúbrica).

    El estándar epistémico ya instruye leer la procedencia que marca el CONTEXTO de cada
    corrida; una afirmación total cableada en el prompt lo contradice y envejece."""
    from shared.narrative.cerebro import AXIS_DOCTRINE

    offenders = []
    for axis, text in AXIS_DOCTRINE.items():
        m = _TOTAL_CLAIMS.search(text)
        if m:
            offenders.append(f"AXIS_DOCTRINE[{axis!r}] :: «…{m.group(0)}…»")
    assert not offenders, (
        "Doctrina(s) del cerebro con afirmación TOTAL de procedencia — el estado por "
        "dimensión viaja en el contexto de cada corrida; el prompt no puede fijarlo:\n  "
        + "\n  ".join(offenders)
    )
