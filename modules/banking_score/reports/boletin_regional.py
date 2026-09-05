"""§4 del boletín regional: la nota metodológica, GENERADA y nunca escrita a mano.

Una nota en prosa envejece con cada conector que se agrega o se cae; la generada no puede
divergir del estado real porque ES el estado real. Hay un gate de CI que impide que el
vocabulario de procedencia vuelva a colarse en la prosa curada
(`shared/knowledge/corpus/tests/test_provenance_vocabulary_gate.py`).
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("sdq.banking_score.boletin_regional")

#: Lo único que se afirma a mano, porque es una decisión editorial y no un estado del dato:
#: por qué la comparación entre países aparece en una sola sección.
_AFIRMACION_DE_METODO = (
    "Los indicadores de cada supervisor nacional se leen **dentro de su propio sistema**: "
    "cada plaza los computa bajo su norma contable y no son comparables entre sí. La única "
    "sección que compara niveles entre países usa las Estadísticas Monetarias y Financieras "
    "Armonizadas (EMFA) del Consejo Monetario Centroamericano, que es lo único que el propio "
    "organismo regional declara armonizado. El corte se declara país por país: las plazas "
    "publican con rezagos muy distintos y un corte único desperdiciaría la frescura de las "
    "más rápidas."
)


def nota_metodologica(db: Session, sector_key: str = "banking") -> str:
    """El texto de §4: la afirmación de método más la procedencia computada del registro."""
    partes = [_AFIRMACION_DE_METODO]
    procedencia = _procedencia(db, sector_key)
    if procedencia:
        partes.append(f"**Procedencia por variable:** {procedencia}")
    return "\n\n".join(partes)


def _procedencia(db: Session, sector_key: str) -> Optional[str]:
    """El párrafo de procedencia del eje, o nada.

    Silencio honesto antes que una afirmación que no podemos sostener: si el registro no
    tiene señal, `provenance_for_sector` devuelve cadena vacía y la nota sale sin ese
    párrafo en vez de con una frase inventada.
    """
    try:
        from shared.registry.provenance import provenance_for_sector

        return provenance_for_sector(db, sector_key) or None
    except Exception as e:  # noqa: BLE001 — la nota no puede tumbar el informe
        logger.warning("[boletín] procedencia no disponible: %s", e)
        return None
