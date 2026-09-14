"""§Limitaciones COMPUTADA: lo que el informe sabe de sí mismo, redactado en código.

**Qué cambia.** Hasta la Fase 4 del plan de entregables mensuales, `limitations` era texto fijo
en cada uno de los quince productos que la declaran: decía lo mismo en un mes con la fuente al
día que en uno con la fuente seis semanas atrasada. Esa sección es la que más debería depender
del período, y era la única que nunca lo hacía.

**Dónde vive.** En el ensamblador, DESPUÉS de la caché y del anexo del delta, y ANTES de
`completar_en_vivo`: el veredicto de una fuente cambia más seguido que el contenido del informe,
así que no puede ir al texto cacheado —es la misma regla que sacó la fecha de descarga del
payload—. Ningún módulo cambia: el texto fijo de cada producto se conserva como PÁRRAFO DE CIERRE
(son las limitaciones de diseño, que no cambian con el mes).

**Qué se escribe y qué no — dos instrucciones del dueño, cumplidas juntas.**

* 2026-08-31 (#1031): lo que no se puede afirmar **no se menciona**; un inventario de faltantes
  desvaloriza el informe. La afirmación de MÉTODO se conserva **una sola vez y en
  §Limitaciones**. Consolidar, no sembrar.
* 2026-09-12 (prompt de las Fases 1 a 8): la sección se computa de las fuentes congeladas o
  indeterminadas, las secciones omitidas, el período del feed contra el del índice y las
  dimensiones sin dato.

De ahí salen las reglas de este archivo:

| señal | se escribe |
|---|---|
| fuente atrasada | el HECHO con su fecha: cuándo publicó el emisor y que la edición siguiente no estaba en nuestra última descarga (el dueño decidió publicarlo el 2026-09-10) |
| frescura indeterminada | que la vigencia de esa fuente no se pudo verificar |
| sección omitida | que la lectura no se incluye en esta edición, **sin** el motivo técnico |
| período del feed ≠ del índice | los dos períodos, nombrados en una frase |
| dimensiones sin dato | **nunca se listan**; si alguna variable está en brecha, UNA vez la frase de método |
| nada que declarar | que el informe no tiene limitaciones de dato propias del período |

Sin claves de máquina (`monthly`, `al_dia`, `gap`) y sin cifras que cambien solas con el
calendario (días de antigüedad): lo que se publica tiene que seguir siendo cierto mañana.

**Nunca rompe la entrega.** Cualquier fallo devuelve las narrativas tal como llegaron.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence

from shared.products.contract import ProductSnapshot
from shared.products.tiers import ProductTier

logger = logging.getLogger("sdq.products.limitaciones")

#: La clave de la sección en los manifiestos.
SECCION = "limitations"

#: La afirmación de método que la decisión del 2026-08-31 reserva para §Limitaciones. Constante:
#: la prosa que debe sobrevivir intacta no vive incrustada (CLAUDE.md).
FRASE_DE_METODO = (
    "Un indicador sin insumo en su fuente se excluye del promedio de su dimensión, y los pesos "
    "se renormalizan sobre lo medido.")

#: Lo que dice un informe sin nada propio del período que declarar. Explícito, no un silencio.
FRASE_SIN_LIMITACIONES = "Este informe no tiene limitaciones de dato propias de este período."

#: La sección del delta, cuando el ensamblador la omitió.
FRASE_DELTA_OMITIDO = "La lectura del movimiento del período no se incluye en esta edición."

#: Separa la parte computada del texto fijo del producto.
SEPARADOR = "\n\n"


def _db_de(product: Any):
    return getattr(product, "db", None) or getattr(product, "_db", None)


def _veredictos(db, sector_key: str) -> List[Any]:
    from shared.operations.fuentes_congeladas import veredictos_del_eje

    return veredictos_del_eje(db, sector_key)


def _feeds(product: Any) -> Dict[str, Any]:
    from shared.products.feed_delta import feeds_del_producto

    return {f.clave: f for f in feeds_del_producto(product)}


def _periodo_en_prosa(periodo: Optional[str]) -> Optional[str]:
    from shared.narrative.formato import mes_largo_es

    if not periodo:
        return None
    return mes_largo_es(periodo) or str(periodo)


def frase_de_feed_atrasado(db, sector_key: str, feed: Any) -> Optional[str]:
    """El atraso de UN feed, con la fecha de publicación del emisor y la de nuestra descarga."""
    from shared.narrative.formato import fecha_larga_es, mes_siguiente
    from shared.observations import service as obs

    ultimo = obs.ultimo_periodo(db, sector_key=sector_key, series=list(feed.series))
    if not ultimo:
        return None
    emisor = feed.emisor_en_prosa or feed.emisor
    leido = _periodo_en_prosa(ultimo)
    falta = _periodo_en_prosa(mes_siguiente(ultimo))
    publicada = obs.ultima_publicacion(db, sector_key=sector_key, series=list(feed.series))
    publicada_txt = fecha_larga_es(publicada.isoformat()) if isinstance(publicada, date) else None
    descarga = (fecha_larga_es(feed.ultima_descarga.isoformat())
                if isinstance(feed.ultima_descarga, date) else None)

    base = f"La lectura mensual de {feed.etiqueta} corresponde a {leido}"
    base += (f", la última edición que publicó {emisor}, el {publicada_txt}"
             if publicada_txt else f", la última edición disponible de {emisor}")
    if falta:
        base += (f"; la de {falta} no figuraba en la fuente en nuestra última descarga, "
                 f"del {descarga}." if descarga else
                 f"; la de {falta} no figuraba en la fuente en nuestra última descarga.")
    else:
        base += "."
    return base


def frase_de_fuente_del_indice_atrasada(veredicto: Any) -> str:
    """El índice cuya fuente no publicó dentro de su ciclo. Sin días: envejecerían solos."""
    from shared.products.report_sections import CADENCIA_ES

    cadencia = CADENCIA_ES.get((veredicto.cadencia or "").lower())
    fuentes = ", ".join(f for f in (veredicto.fuentes or ()) if f)
    sujeto = f"La fuente del índice ({fuentes})" if fuentes else "La fuente del índice"
    ciclo = f" dentro de su ciclo {cadencia}" if cadencia else ""
    return (f"{sujeto} no publicó una edición nueva{ciclo}: el índice de este informe se "
            f"construye sobre su último corte disponible.")


def frase_de_vigencia_no_verificada(etiqueta: str) -> str:
    return (f"No fue posible verificar la vigencia de {etiqueta}; sus cifras se presentan con el "
            f"corte que declara la propia fuente.")


def frase_de_periodos(snapshot: ProductSnapshot, lecturas: Sequence[Any]) -> Optional[str]:
    """El índice y la lectura mensual miden períodos distintos: se nombran los dos, una vez."""
    periodos = sorted({p for p in lecturas if p})
    if not periodos or not snapshot.period:
        return None
    meses = " y ".join(_periodo_en_prosa(p) or p for p in periodos)
    return (f"El índice de este informe corresponde a {snapshot.period}; la lectura mensual, a "
            f"{meses}. Son cortes distintos y no se suman.")


def _hay_brecha(product: Any) -> bool:
    """¿Alguna variable del eje está en brecha? Solo con la señal del registro, nunca inferida."""
    from shared.registry.signals import GAP

    declarar = getattr(product, "variable_signals", None)
    if not callable(declarar):
        return False
    crudo = declarar()
    senales: Iterable[Any] = (crudo.get("signals", ()) if isinstance(crudo, dict)
                              else (crudo or ()))
    return any(getattr(s, "state", None) == GAP for s in senales)


def limitaciones_computadas(product: Any, tier: ProductTier, snapshot: ProductSnapshot,
                            secciones_omitidas: Sequence[Dict[str, str]] = ()) -> str:
    """La parte computada de §Limitaciones. Siempre devuelve texto: vacío no existe."""
    from shared.operations.fuentes_congeladas import CONGELADA, INDETERMINADA
    from shared.observations import service as obs

    frases: List[str] = []
    db = _db_de(product)
    sector_key = str(getattr(product, "sector_key", "") or "")
    feeds = _feeds(product)

    if db is not None and sector_key:
        for v in _veredictos(db, sector_key):
            clave = getattr(v, "clave", "") or ""
            if v.estado == CONGELADA:
                if clave and clave in feeds:
                    frase = frase_de_feed_atrasado(db, sector_key, feeds[clave])
                    if frase:
                        frases.append(frase)
                elif not clave:
                    frases.append(frase_de_fuente_del_indice_atrasada(v))
            elif v.estado == INDETERMINADA:
                etiqueta = (feeds[clave].etiqueta if clave in feeds
                            else (getattr(v, "etiqueta", "") or "la fuente del índice"))
                frases.append(frase_de_vigencia_no_verificada(etiqueta))

        lecturas = []
        for feed in feeds.values():
            try:
                lecturas.append(obs.ultimo_periodo(db, sector_key=sector_key,
                                                   series=list(feed.series)))
            except Exception:  # noqa: BLE001 — un feed ilegible no aporta período
                continue
        frase = frase_de_periodos(snapshot, lecturas)
        if frase:
            frases.append(frase)

    from shared.products.feed_delta import SECCION_DELTA

    if any(o.get("seccion") == SECCION_DELTA for o in secciones_omitidas or ()):
        frases.append(FRASE_DELTA_OMITIDO)

    if _hay_brecha(product):
        frases.append(FRASE_DE_METODO)

    return " ".join(frases) if frases else FRASE_SIN_LIMITACIONES


def completar_limitaciones(product: Any, tier: ProductTier, snapshot: ProductSnapshot,
                           narratives: Dict[str, str],
                           secciones_omitidas: Sequence[Dict[str, str]] = ()) -> Dict[str, str]:
    """Antepone la parte computada al texto fijo de §Limitaciones, si el nivel la trae.

    Nunca modifica el dict que recibe y nunca lanza: ante cualquier fallo, la sección sale
    con su texto fijo, como antes.
    """
    fijo = narratives.get(SECCION)
    if not isinstance(fijo, str):
        return narratives
    try:
        computado = limitaciones_computadas(product, tier, snapshot, secciones_omitidas)
    except Exception:  # noqa: BLE001 — la sección nunca tumba la entrega
        logger.exception("Limitaciones computadas de %s fallaron; se sirve el texto fijo",
                         getattr(product, "sector_key", "?"))
        return narratives
    texto = f"{computado}{SEPARADOR}{fijo}" if fijo.strip() else computado
    return {**narratives, SECCION: texto}
