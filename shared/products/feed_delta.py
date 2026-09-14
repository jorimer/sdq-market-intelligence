"""La sección del MOVIMIENTO DEL MES, transversal: la narra el ENSAMBLADOR, con caché propia.

**Qué es.** Un eje cuyo índice es anual puede recibir además un feed sub-anual —las licencias
mensuales del MIVHED, la afiliación mensual de la SISALRIL—. El movimiento de ese feed contra
su línea base se COMPUTA en ``shared/observations/delta.py`` y se NARRA acá, como una sección
más del informe (``delta_mensual``), que las tres superficies —app, PDF, Word— heredan sin que
cada módulo tenga que escribir 300 líneas.

**Por qué vive en ``shared/`` y no en el módulo.** Hasta la Fase 1 del plan de entregables
mensuales el delta de construcción se narraba dentro de ``construction_intel/products.py`` y
su bloque iba al PAYLOAD del informe. Funcionaba, y tenía un costo que no se veía: la huella de
``ProductReportCache`` es del payload entero, así que cada mes nuevo del feed regeneraba el Deep
Dive COMPLETO —seis llamadas al modelo por un dato que solo cambia una sección—. Y el segundo
eje con feed habría copiado el mecanismo entero.

**Qué declara el producto.** Un método opcional ``feeds_mensuales() -> list[FeedDeclarado]``
(detectado por ``getattr``, como el resto del contrato opcional): qué series, de qué emisor,
con qué cadencia, con qué nota de dominio. Nada más: no toca ``render()``, no toca
``narratives()``, no toca el payload. Un producto sin feeds no cambia en nada.

**Caché propia, por sección.** ``FeedDeltaCache`` se indexa por (eje, feed, período del feed,
nivel, idioma) y su huella cubre el CONTEXTO que ve el modelo, la RECETA (la misma que ya
calcula el ensamblador: plantillas, doctrina, modelo, guard, saneador) y este archivo, que es
donde se arma el contexto. El delta se regenera solo cuando cambia SU período o SU receta; el
informe del índice no se entera y sigue siendo HIT.

**Lo vivo no entra ni al contexto ni a la huella.** El encabezado nombra la fecha de la última
DESCARGA de la fuente, que la sonda mueve a diario. Se antepone al servir, en cada entrega,
sobre el texto cacheado — nunca se guarda. Con la fecha en la huella, el delta se regeneraría
cada día sin que el dato cambie. Es la misma decisión que llevó a ``completar_en_vivo``.

**Lo que esta sección NO puede afirmar.** Lee el movimiento y su magnitud; **no explica su
causa**. No hay citación por oración en este producto —la atribución es por sección y
fuente—, así que «la caída responde a X» es lo que el gate no puede respaldar. La regla va en
la plantilla y, además, se VERIFICA sobre el texto generado: una afirmación causal omite la
sección (y la lista como omitida). Ver ``frases_causales``.

**Nunca empeora el informe.** Si el motor está degradado, si el texto trae una cifra sin
respaldo, si no queda tiempo del presupuesto de ensamblado o si el feed no se puede leer, la
sección se OMITE y se LISTA (``ProductContent.secciones_omitidas``) — no tumba el informe del
índice, que no depende de ella. Lo omitido no desaparece: un veto silencioso se lee como que el
eje no tiene feed.

**Con la fuente atrasada se PUBLICA, con el mes nombrado** (decisión del dueño, 2026-09-10).
La lectura nombra su período, así que no se hace pasar por el mes en curso; y que el emisor
lleve semanas sin publicar es en sí información. Solo ``indeterminada`` veta: sin saber cuándo
publicó la fuente no hay declaración honesta que poner al lado.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import pathlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from shared.products.contract import ProductSnapshot
from shared.products.tiers import ProductTier

logger = logging.getLogger("sdq.products.feed_delta")

_UN_DIA = timedelta(days=1)

#: La clave de la sección en el informe. Cada producto con feeds la titula en su
#: ``_SECTION_TITLES`` (el PDF) y la app en ``platform.catalog.section`` (por eje si el nombre
#: difiere). Lo exige ``test_feed_delta.py`` y ``test_toda_seccion_tiene_titulo_en_la_app.py``.
SECCION_DELTA = "delta_mensual"
#: La plantilla del motor. Es THIN (ruta cerebro): el eje se pasa en ``FeedDeclarado.axis``.
PLANTILLA = "feed_delta"
MODO = "standard"
#: Por debajo de esto no se intenta narrar: el delta no puede empujar el ensamblado por encima
#: del proxy. Una llamada al modelo con guard toma 15-30 s; con menos, se omite por tiempo.
MINIMO_PARA_NARRAR_S = 30.0

# ── Motivos por los que la sección se omite. Se LISTAN en `ProductContent.secciones_omitidas`.
OMITIDA_DEGRADADA = "degradada"
OMITIDA_SIN_RESPALDO = "cifra_sin_respaldo"
OMITIDA_CAUSAL = "afirmacion_causal"
OMITIDA_TIEMPO = "tiempo"
OMITIDA_ILEGIBLE = "feed_no_legible"

#: La prosa que el modelo debe respetar vive en CONSTANTES (CLAUDE.md): un literal partido por
#: ancho de línea deja de existir en el fuente y un test que lo busque falla sin motivo.
REGLA_DE_ALCANCE = (
    "Esta sección LEE el movimiento y su magnitud. NO explica su causa: la atribución de este "
    "producto es por sección y fuente, no por oración, así que una afirmación causal no "
    "tendría con qué respaldarse.")
NOTA_GENERAL = (
    "Cada lectura es el movimiento de UN emisor en SU período contra la línea base que su "
    "naturaleza exige: un flujo contra el mismo período del año anterior (la serie tiene "
    "estación); un stock contra el último nivel publicado; una tasa o un índice en puntos. La "
    "ventana móvil de doce meses, cuando viene, es la magnitud comparable con el índice anual "
    "de este informe.")

#: Frases con las que un texto AFIRMA una causa. Si el modelo escribe alguna, la sección no se
#: publica: el gate no puede respaldar una afirmación causal (§0.3 del plan).
FRASES_CAUSALES: Tuple[str, ...] = (
    "debido a", "responde a", "responden a", "por efecto de", "explicado por", "explicada por",
    "se explica por", "se explican por", "a causa de", "como consecuencia de", "gracias a",
    "impulsado por", "impulsada por", "impulsados por", "impulsadas por", "producto de",
    "a raíz de", "obedece a", "obedecen a",
)


@dataclass(frozen=True)
class Dimension:
    """Un desglose del feed por una dimensión del microdato (provincia, tipología).

    ``clave_de_contexto`` nombra su SUJETO y su período —``metros_cuadrados_licenciados_por_
    provincia_del_mes``, nunca ``por_provincia``—: el modelo reatribuye al sujeto más cercano.
    """

    clave_de_contexto: str
    serie: str
    campo: str            # "provincia" | "tipologia"
    top: int = 5


@dataclass(frozen=True)
class FeedDeclarado:
    """Lo que un producto declara de UN feed sub-anual para que el ensamblador lo narre.

    ``clave`` es la misma con la que el sensor de fuentes congeladas identifica la fuente
    (``SenalDeFuente.clave``): el veredicto de frescura se lee por ella. ``series`` son los
    códigos de ``sector_observations`` que componen el feed; ``etiquetas`` los rotula.

    ``ultima_descarga`` es lo VIVO: cuándo bajamos la fuente por última vez. Se cita en el
    encabezado y **no entra a la huella de la caché** — lo vigila ``test_feed_delta.py``.
    """

    clave: str
    etiqueta: str                       # "MIVHED · licencias emitidas" (panel y metodología)
    emisor: str                         # "MIVHED (datos.gob.do)" — cómo se cita
    series: Tuple[str, ...]
    etiquetas: Mapping[str, str]
    axis: str                           # eje del cerebro ("construction_intel")
    emisor_en_prosa: str = ""           # "el MIVHED" — con artículo, para la frase de atraso
    fuente: Any = None                  # `shared.narrative.atribucion.Fuente` (licencia)
    cadence: str = "monthly"
    nota: str = ""                      # qué mide el dato y qué no (indicador líder, stock…)
    dimensiones: Tuple[Dimension, ...] = ()
    ultima_descarga: Optional[date] = None
    audience: str = "inversionista"


# ── Declaración ──────────────────────────────────────────────────────────────────────

def feeds_del_producto(product: Any) -> List[FeedDeclarado]:
    """Los feeds que *product* declara, o ``[]``. Nunca lanza: un producto que revienta al
    declarar no tiene feed, no tiene sección, y el informe del índice sigue."""
    declarar = getattr(product, "feeds_mensuales", None)
    if not callable(declarar):
        return []
    try:
        return [f for f in (declarar() or []) if isinstance(f, FeedDeclarado)]
    except Exception:  # noqa: BLE001 — la sección jamás tumba el informe
        logger.exception("feeds_mensuales de %s falló; se sirve sin delta",
                         getattr(product, "sector_key", "?"))
        return []


def fin_del_periodo(periodo: Optional[str]) -> Optional[date]:
    """El último día de ``AAAA-MM`` / ``AAAA-QN`` / ``AAAA``; ``None`` si no se sabe leer."""
    p = str(periodo or "").strip()
    try:
        if len(p) == 4 and p.isdigit():
            return date(int(p), 12, 31)
        if len(p) == 7 and p[4] == "-" and p[5:].isdigit():
            a, m = int(p[:4]), int(p[5:])
            if not 1 <= m <= 12:
                return None
            return date(a + (m == 12), 1 if m == 12 else m + 1, 1) - _UN_DIA
        if len(p) == 7 and p[4:6] == "-Q" and p[6].isdigit():
            a, q = int(p[:4]), int(p[6])
            if not 1 <= q <= 4:
                return None
            m = q * 3
            return date(a + (m == 12), 1 if m == 12 else m + 1, 1) - _UN_DIA
    except ValueError:
        return None
    return None



def dias_desde_el_fin_del_periodo(periodo: Optional[str], hoy: Optional[date] = None
                                  ) -> Optional[int]:
    """La antigüedad del PERÍODO del dato, no de la fila: un sync que corre en verde contra un
    archivo que ya no se actualiza no mueve el período."""
    fin = fin_del_periodo(periodo)
    if fin is None:
        return None
    return max(0, ((hoy or date.today()) - fin).days)


def senales_de_los_feeds(db: Session, sector_key: str,
                         feeds: Sequence[FeedDeclarado]) -> List[Any]:
    """Las ``SenalDeFuente`` de los feeds, para el sensor de fuentes congeladas.

    Un producto las devuelve desde ``senales_de_fuentes()``; así el sensor y esta sección
    juzgan la frescura con el MISMO criterio (``fuentes_congeladas.evaluar_fuente``).
    """
    from shared.observations import service as obs
    from shared.operations.fuentes_congeladas import SenalDeFuente

    salida: List[Any] = []
    for feed in feeds:
        try:
            ultimo = obs.ultimo_periodo(db, sector_key=sector_key, series=list(feed.series),
                                        con_valor=True)
        except Exception as e:  # noqa: BLE001 — sin feed no hay señal, no hay error
            logger.warning("feed «%s» de %s no legible: %s", feed.clave, sector_key, e)
            continue
        if not ultimo:
            continue
        salida.append(SenalDeFuente(
            clave=feed.clave, etiqueta=feed.etiqueta, cadence=feed.cadence,
            freshness_days=dias_desde_el_fin_del_periodo(ultimo),
            detalle=f"último período observado: {ultimo}"))
    return salida


# ── El bloque computado ──────────────────────────────────────────────────────────────

def motivo_en_castellano(veredicto: Any) -> str:
    """El porqué del veto, redactado para el CLIENTE.

    El ``motivo`` del veredicto está escrito para el operador y arrastra la clave de máquina
    de la cadencia (``monthly``): pegarlo publicaba «su fuente (monthly)» dentro de un
    documento en español. Los HECHOS se copian; la frase se escribe acá.
    """
    from shared.products.report_sections import CADENCIA_ES

    if veredicto is None:
        return ("el eje no declara este feed, así que no hay veredicto de frescura que lo "
                "respalde")
    cad = CADENCIA_ES.get((veredicto.cadencia or "").lower(), veredicto.cadencia or "—")
    dias = veredicto.dias_desde_el_periodo_del_dato
    tope = veredicto.tope_de_dias_de_la_cadencia
    if dias is None or tope is None:
        return ("no se pudo determinar la antigüedad del dato de esta fuente, y una frescura "
                "indeterminada no es una frescura verificada")
    return (f"el dato más reciente de esta fuente de cadencia {cad} tiene {dias} días, cuando "
            f"una edición nueva debía haber aparecido a los {tope}")


def bloque_del_feed(db: Session, sector_key: str, feed: FeedDeclarado) -> Optional[Dict[str, Any]]:
    """La lectura de UN feed en su último período observado, o ``None`` si no tiene ninguno.

    Devuelve ``{"no_publicable": motivo, ...}`` cuando la frescura de la fuente es
    indeterminada: ahí no hay declaración honesta que poner al lado de la lectura.
    """
    from shared.observations import service as obs
    from shared.observations.delta import leer_delta
    from shared.operations.fuentes_congeladas import (
        AL_DIA, CONGELADA, veredicto_de_la_fuente)
    from shared.products.report_sections import CADENCIA_ES

    # Con valor: un período cuyas filas son todas NULL no es una edición publicada. El sensor
    # (`senales_de_los_feeds`) lee el mismo período, así que la sección y el panel no se
    # contradicen.
    ultimo = obs.ultimo_periodo(db, sector_key=sector_key, series=list(feed.series),
                                con_valor=True)
    if not ultimo:
        return None
    cabecera = {"clave": feed.clave, "etiqueta": feed.etiqueta, "emisor": feed.emisor}
    veredicto = veredicto_de_la_fuente(db, sector_key=sector_key, clave=feed.clave)
    if veredicto is None or veredicto.estado not in (AL_DIA, CONGELADA):
        return {**cabecera, "no_publicable": motivo_en_castellano(veredicto),
                "ultimo_periodo_observado": ultimo}
    bloque = leer_delta(db, sector_key=sector_key, period=ultimo,
                        series=list(feed.series), etiquetas=dict(feed.etiquetas))
    bloque.update(cabecera)
    # La frescura de la FUENTE, como dato. Sin `dias`: una cifra calculada contra hoy
    # cambiaría la huella cada día sin que el dato cambie. Lo estable es el período, la fecha
    # de publicación y el veredicto — que cambia, a lo sumo, una vez por edición.
    publicada = obs.ultima_publicacion(db, sector_key=sector_key, series=list(feed.series))
    bloque["fuente_del_feed"] = {
        "al_dia": veredicto.estado == AL_DIA,
        "ultimo_periodo": ultimo,
        "ultima_publicacion": publicada.isoformat() if publicada else None,
        "cadencia": CADENCIA_ES.get(feed.cadence, feed.cadence),
    }
    dimensiones: Dict[str, Any] = {}
    for dim in feed.dimensiones:
        dimensiones[dim.clave_de_contexto] = obs.por_dimension(
            db, sector_key=sector_key, series_code=dim.serie, period=ultimo,
            campo=dim.campo)[:dim.top]
    bloque["dimensiones"] = dimensiones
    return bloque


def bloque_del_delta(db: Session, sector_key: str,
                     feeds: Sequence[FeedDeclarado]) -> Optional[Dict[str, Any]]:
    """El bloque de la sección: una lectura por feed publicable y los vetados con su motivo.

    ``None`` si ningún feed tiene observaciones — y entonces la sección NO aparece (no aparece
    vacía). Con varios emisores para el mismo eje cada uno viaja con SU período: no se
    promedian ni se elige uno.
    """
    lecturas: List[Dict[str, Any]] = []
    no_publicables: List[Dict[str, Any]] = []
    for feed in feeds:
        b = bloque_del_feed(db, sector_key, feed)
        if b is None:
            continue
        (no_publicables if "no_publicable" in b else lecturas).append(b)
    if not lecturas and not no_publicables:
        return None
    return {
        "periodo": max((b["periodo"] for b in lecturas), default=None),
        "lecturas": lecturas,
        "no_publicables": [{"clave": b["clave"], "etiqueta": b["etiqueta"],
                            "emisor": b["emisor"], "motivo": b["no_publicable"],
                            "ultimo_periodo_observado": b.get("ultimo_periodo_observado")}
                           for b in no_publicables],
    }


# ── El contexto que ve el modelo ─────────────────────────────────────────────────────

def _periodo_en_prosa(periodo: Optional[str]) -> str:
    from shared.narrative.formato import mes_largo_es
    return mes_largo_es(periodo) or str(periodo or "")


#: Cómo se lee una ventana de doce meses que no tiene la del año anterior para compararse. Constante
#: y no literal: una frase partida por ancho de línea deja de existir en el fuente.
LECTURA_DE_LA_VENTANA_SIN_BASE = (
    "Es el total de los doce meses y se nombra como total. No se compara con nada: no escribas "
    "variación, línea base ni que la comparación no existe o no está disponible."
)


def _serie_para_el_modelo(serie: Dict[str, Any]) -> Dict[str, Any]:
    """La serie sin lo que NO se pudo computar de su ventana de doce meses.

    `shared/observations/delta.py` declara el motivo cuando la ventana o su base del año anterior no
    existen («faltan 5 de los 12 meses»), y eso queda en el DATO. Pero puesto en el contexto, el
    modelo lo narra, y el documento termina declarando un hueco —lo que la decisión del dueño del
    2026-08-31 prohíbe—. Salió así en prod en energía y construcción (2026-09-14). Acá:
    * ventana no disponible → la clave no viaja;
    * ventana disponible sin base anterior → viaja el total, sin la base.
    """
    ventana = serie.get("ventana_movil_12m")
    if not isinstance(ventana, dict):
        return serie
    limpia = {k: v for k, v in serie.items() if k != "ventana_movil_12m"}
    if not ventana.get("disponible"):
        return limpia
    base = ventana.get("linea_base")
    if isinstance(base, dict) and "no_disponible" in base:
        # Sin la base, el modelo igual notaba que esta ventana no se compara y la otra serie de la
        # misma sección sí, y lo decía: «No se dispone de línea base para la ventana móvil en esta
        # fuente» (construcción, 2026-09-14, tras quitar el motivo). Se le dice cómo leerla.
        ventana = {**{k: v for k, v in ventana.items() if k != "linea_base"},
                   "se_lee_como": LECTURA_DE_LA_VENTANA_SIN_BASE}
    return {**limpia, "ventana_movil_12m": ventana}


def contexto_del_delta(bloque: Dict[str, Any], feeds: Sequence[FeedDeclarado],
                       periodo_del_informe: str) -> Dict[str, Any]:
    """Bloque CERRADO: el modelo lo copia.

    Todas las relaciones vienen resueltas (dirección, variación con su medida, línea base y
    su tipo) de ``shared/observations/delta.py``; acá se reetiquetan. Cada cifra viaja con su
    sujeto y su medida. Lo que no se pudo leer NO viaja: el bloque lo conserva
    (``sin_lectura``), pero una serie sin valor puesta en el contexto el modelo la narra como
    ausencia, y el documento no declara huecos (decisión del dueño, 2026-08-31). Llegó a prod:
    «el margen de solvencia requerido del sistema no cuenta con observación».

    **No lleva la fecha de la última descarga**: es lo vivo, y lo vivo no entra a la huella.
    """
    from shared.narrative.formato import fecha_larga_es

    por_clave = {f.clave: f for f in feeds}
    lecturas = []
    for b in bloque.get("lecturas") or []:
        feed = por_clave.get(b["clave"])
        fuente = b.get("fuente_del_feed") or {}
        lecturas.append({
            "emisor_del_movimiento": b["emisor"],
            "etiqueta_del_feed": b["etiqueta"],
            "periodo_del_movimiento": b["periodo"],
            # El período ESCRITO, para que el modelo lo nombre igual que el encabezado y no
            # traduzca "2026-06" por su cuenta.
            "periodo_leido": _periodo_en_prosa(b["periodo"]),
            # Si la fuente está atrasada, el encabezado ya lo declara. Estos dos campos existen
            # para que la prosa NO lo contradiga («la lectura más reciente», «este mes»), no
            # para que lo repita.
            "fuente_al_dia": bool(fuente.get("al_dia", True)),
            "ultima_publicacion_de_la_fuente": fecha_larga_es(fuente.get("ultima_publicacion")),
            "series_del_periodo": [_serie_para_el_modelo(s) for s in (b.get("series") or [])],
            **(b.get("dimensiones") or {}),
            "nota_del_emisor": feed.nota if feed else "",
        })
    fuentes = [f.fuente for f in feeds if f.fuente is not None]
    return {
        "periodo_del_indice_anual_del_informe": periodo_del_informe,
        "lecturas_por_emisor": lecturas,
        "lecturas_no_publicables": [{"emisor": n["emisor"], "motivo": n["motivo"]}
                                    for n in bloque.get("no_publicables") or []],
        **_atribucion_del_delta(fuentes),
        "regla_de_alcance": REGLA_DE_ALCANCE,
        "note": NOTA_GENERAL,
    }


#: Qué se le dice al modelo en el delta cuando la licencia EXIGE nombrar a la fuente. El aviso lo
#: pone el CÓDIGO al pie: pedírselo al modelo lo dejó dos veces en el Deep Dive de seguros en prod
#: (2026-09-14), una por subsección, y la segunda bajo el bloque de las ARS nombrando al SFS.
REGLA_DE_LA_ATRIBUCION_DEL_DELTA = (
    "El aviso de `atribucion_obligatoria` lo agrega el sistema al pie de esta sección, una sola "
    "vez y con el texto exacto: NO escribas ninguna línea de fuente ni ese aviso."
)


def _atribucion_del_delta(fuentes: Sequence[Any]) -> Dict[str, str]:
    """Las claves de procedencia del contexto, con la regla del delta si hay aviso exigido."""
    from shared.narrative.atribucion import bloque_de_atribucion

    bloque = bloque_de_atribucion(*fuentes)
    if bloque["atribucion_obligatoria"]:
        bloque["regla_de_la_atribucion"] = REGLA_DE_LA_ATRIBUCION_DEL_DELTA
    return bloque


def _textos_de_atribucion(feeds: Sequence[FeedDeclarado]) -> List[str]:
    """Los avisos que las licencias de los feeds exigen, sin repetir y en orden."""
    textos = (getattr(f.fuente, "atribucion", "") for f in feeds if f.fuente is not None)
    return [t for t in dict.fromkeys(textos) if t]


def _plano(texto: str) -> str:
    return " ".join(re.sub(r"[*_`]", " ", str(texto or "")).lower().split())


def pie_de_atribucion(feeds: Sequence[FeedDeclarado]) -> str:
    """El aviso que la licencia exige, una vez y con su texto exacto. Vacío si no exige ninguno."""
    return "\n".join(f"*{t}*" for t in _textos_de_atribucion(feeds))


def sin_lineas_de_atribucion(texto: str, feeds: Sequence[FeedDeclarado]) -> str:
    """El texto del modelo sin las líneas de fuente que haya escrito, cuando el pie las pone.

    Se aplica al SERVIR y no al generar: así corrige también los textos que ya están en caché.
    Sin aviso exigido no toca nada — ahí la cita la escribe el modelo y no hay pie que la repita.
    """
    avisos = [_plano(t) for t in _textos_de_atribucion(feeds)]
    if not avisos:
        return texto
    lineas: List[str] = []
    for linea in str(texto or "").splitlines():
        plano = _plano(linea)
        if plano and (any(a in plano for a in avisos) or plano.startswith("fuente:")):
            continue
        lineas.append(linea)
    # El separador que quedó huérfano al final, y los blancos que dejó lo quitado.
    while lineas and lineas[-1].strip() in ("", "---"):
        lineas.pop()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


# ── La prosa determinista: encabezado y veto ─────────────────────────────────────────

def encabezado_del_movimiento(bloque: Dict[str, Any], feeds: Sequence[FeedDeclarado]) -> str:
    """El período nombrado y, por cada fuente atrasada, la declaración. Determinista.

    Va en CÓDIGO y no pedido al modelo: una declaración que tiene que aparecer no puede
    depender de que el narrador se acuerde. Todo sale del dato — ninguna fecha a mano.

    **Afirma solo lo que se sabe.** No dice que la edición siguiente «no figura en la fuente»:
    eso es el estado ACTUAL de la fuente, y lo único verificado es que no estaba en la ÚLTIMA
    DESCARGA. Por eso la frase nombra esa descarga y su fecha.
    """
    from shared.narrative.formato import de_seguido_de, fecha_larga_es, mes_siguiente

    lecturas = bloque.get("lecturas") or []
    if not lecturas:
        return ""
    por_clave = {f.clave: f for f in feeds}
    periodos = {b["periodo"] for b in lecturas}
    if len(periodos) == 1:
        lead = f"Movimiento de {_periodo_en_prosa(lecturas[0]['periodo'])}."
    else:
        partes = [f"{_periodo_en_prosa(b['periodo'])} según {b['emisor']}" for b in lecturas]
        lead = "Movimiento de " + ", ".join(partes) + "."
    frases = [lead]
    for b in lecturas:
        fuente = b.get("fuente_del_feed") or {}
        if fuente.get("al_dia", True):
            continue
        feed = por_clave.get(b["clave"])
        emisor = (feed.emisor_en_prosa if feed and feed.emisor_en_prosa else b["emisor"])
        cadencia = fuente.get("cadencia") or "mensual"
        publicada = fecha_larga_es(fuente.get("ultima_publicacion"))
        falta = _periodo_en_prosa(mes_siguiente(fuente.get("ultimo_periodo")))
        descarga = (fecha_larga_es(feed.ultima_descarga.isoformat())
                    if feed and isinstance(feed.ultima_descarga, date) else None)
        if not falta:
            continue
        no_estaba = (f"la de {falta}, de cadencia {cadencia}, no figuraba en la fuente en "
                     f"nuestra última descarga, del {descarga}." if descarga else
                     f"la de {falta}, de cadencia {cadencia}, no figuraba en la fuente en "
                     f"nuestra última descarga.")
        if publicada:
            frases.append(f"Es la última edición que publicó {emisor}, el {publicada}; {no_estaba}")
        else:
            frases.append(f"Es la última edición disponible {de_seguido_de(emisor)}; {no_estaba}")
    return " ".join(frases)


def texto_del_veto(bloque: Dict[str, Any]) -> str:
    """Prosa determinista cuando NINGÚN feed es publicable. NOMBRA la causa: un bloque que dice
    «no disponible» y calla el porqué se lee como un fallo nuestro, y acá el hecho es del
    emisor."""
    motivos = "; ".join(n["motivo"] for n in bloque.get("no_publicables") or [])
    return (f"No se publica la lectura del movimiento del mes: {motivos}. El índice anual de "
            f"este informe no depende de este feed y no se ve afectado.")


def nota_de_los_no_publicables(bloque: Dict[str, Any]) -> str:
    """Cuando un feed SÍ se publica y otro no, el otro se declara al pie. Nunca desaparece."""
    partes = [f"La lectura de {n['etiqueta']} no se publica: {n['motivo']}."
              for n in bloque.get("no_publicables") or []]
    return " ".join(partes)


def frases_causales(texto: str) -> List[str]:
    """Las frases con las que *texto* afirma una causa, en orden de aparición. Vacío = limpio."""
    t = " ".join(str(texto or "").lower().split())
    halladas: List[str] = []
    for frase in FRASES_CAUSALES:
        if re.search(r"(?<![\wáéíóúñ])" + re.escape(frase) + r"(?![\wáéíóúñ])", t):
            halladas.append(frase)
    return halladas


# ── Caché propia ─────────────────────────────────────────────────────────────────────

def _huella_de_este_archivo() -> str:
    """Este archivo ARMA el contexto: es al delta lo que ``ai_context.py`` es al índice."""
    try:
        return hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


def huella_del_delta(contexto: Dict[str, Any], tier: str, lang: str) -> str:
    """Contexto + nivel + idioma + RECETA (la misma huella que el ensamblador) + este archivo."""
    from shared.products.assembler import NARRATIVE_CACHE_VERSION, _narrative_logic_version

    raw = json.dumps(contexto, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(
        f"{raw}|{tier}|{lang}|{NARRATIVE_CACHE_VERSION}|{_narrative_logic_version()}|"
        f"{_huella_de_este_archivo()}".encode("utf-8")).hexdigest()


def _clave_de_cache(bloque: Dict[str, Any]) -> Tuple[str, str]:
    lecturas = bloque.get("lecturas") or []
    return ("+".join(b["clave"] for b in lecturas), "+".join(b["periodo"] for b in lecturas))


def _leer_cache(db: Session, key: Dict[str, str], fp: str) -> Optional[str]:
    from shared.narrative.claude_engine import is_static_fallback_text
    from shared.products.models import FeedDeltaCache

    try:
        row = db.query(FeedDeltaCache).filter_by(**key).first()
    except Exception as e:  # noqa: BLE001 — la caché jamás tumba la entrega
        logger.warning("caché del delta (lectura) no disponible: %s", e)
        return None
    if row is None or row.fingerprint != fp or not row.texto:
        return None
    if is_static_fallback_text(row.texto):
        logger.warning("caché del delta HIT DEGRADADA en %s: se ignora y regenera", key)
        return None
    return str(row.texto)


def _escribir_cache(db: Session, key: Dict[str, str], fp: str, texto: str) -> None:
    from shared.products.models import FeedDeltaCache

    try:
        row = db.query(FeedDeltaCache).filter_by(**key).first()
        if row is None:
            row = FeedDeltaCache(**key)
            db.add(row)
        row.fingerprint = fp
        row.texto = texto
        db.commit()
    except Exception as e:  # noqa: BLE001 — una carrera/constraint no rompe la entrega
        db.rollback()
        logger.warning("caché del delta (escritura) omitida: %s", e)


# ── El punto de entrada del ensamblador ──────────────────────────────────────────────

def _omitida(motivo: str, detalle: str) -> Dict[str, str]:
    return {"seccion": SECCION_DELTA, "motivo": motivo, "detalle": detalle}


async def _narrar(contexto: Dict[str, Any], feed: FeedDeclarado, lang: str,
                  presupuesto_s: Optional[float]) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    """Una llamada al modelo, con sus propios acumuladores del guard. (texto, omisión)."""
    from shared.narrative import cifras_pendientes, relaciones_pendientes
    from shared.narrative.claude_engine import is_static_fallback_text, narrative_engine
    from shared.narrative.presupuesto import con_presupuesto

    # Cajas PROPIAS: lo que el guard marque acá se decide acá. Con las cajas del ensamblado
    # del índice, una cifra sin respaldo en el delta vetaría el informe premium entero — y
    # el índice no depende del feed.
    with cifras_pendientes.acumulando() as sin_respaldo, \
            relaciones_pendientes.acumulando() as relaciones, \
            con_presupuesto(presupuesto_s):
        try:
            res = await asyncio.wait_for(
                narrative_engine.generate(context=contexto, template=PLANTILLA, mode=MODO,
                                          lang=lang, axis=feed.axis, audience=feed.audience),
                timeout=presupuesto_s)
        except asyncio.TimeoutError:
            return None, _omitida(OMITIDA_TIEMPO,
                                  f"la narración no entró en los {presupuesto_s or 0:.0f} s "
                                  f"que quedaban del presupuesto de ensamblado")
    texto = res.text
    if is_static_fallback_text(texto):
        return None, _omitida(OMITIDA_DEGRADADA, "el motor cayó al texto de respaldo")
    if sin_respaldo:
        return None, _omitida(OMITIDA_SIN_RESPALDO,
                              "el texto afirma cifras que el contexto no sostiene: "
                              + "; ".join(h for hs in sin_respaldo.values() for h in hs))
    causales = frases_causales(texto)
    if causales:
        return None, _omitida(OMITIDA_CAUSAL,
                              "el texto explica una causa («" + "», «".join(causales)
                              + "») y esta sección solo puede leer el movimiento")
    if relaciones:
        logger.warning("delta con relaciones que el dato contradice (se entrega y se "
                       "registra, misma política que el informe): %s", relaciones)
    return texto, None


async def anexar_delta_de_feeds(
    product: Any, tier: ProductTier, snapshot: ProductSnapshot,
    narratives: Dict[str, str], lang: str = "es", *,
    presupuesto_restante_s: Optional[float] = None,
) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
    """Anexa la sección del delta a *narratives* si el producto declara feeds con observaciones.

    Devuelve ``(narrativas, secciones_omitidas)``. Nunca lanza y nunca modifica el dict que
    recibe. Sin feeds, sin observaciones o sin sesión de base: las narrativas salen IDÉNTICAS
    y la sección no aparece.
    """
    feeds = feeds_del_producto(product)
    if not feeds:
        return narratives, []
    db = getattr(product, "db", None) or getattr(product, "_db", None)
    if db is None:
        return narratives, []
    sector_key = str(getattr(product, "sector_key", "") or "")
    try:
        bloque = bloque_del_delta(db, sector_key, feeds)
    except Exception as e:  # noqa: BLE001 — el informe del índice nunca depende del feed
        logger.exception("delta de %s no legible; se omite", sector_key)
        return narratives, [_omitida(OMITIDA_ILEGIBLE, f"no se pudo leer el feed: {e}")]
    if bloque is None:
        return narratives, []
    if not bloque["lecturas"]:
        # Todo vetado: prosa determinista, sin modelo. Se publica el porqué.
        return {**narratives, SECCION_DELTA: texto_del_veto(bloque)}, []

    contexto = contexto_del_delta(bloque, feeds, snapshot.period)
    fp = huella_del_delta(contexto, tier.value, lang)
    clave, periodo = _clave_de_cache(bloque)
    key = dict(sector_key=sector_key, feed_clave=clave, feed_period=periodo,
               tier=tier.value, lang=lang)
    texto = _leer_cache(db, key, fp)
    if texto is not None:
        logger.info("caché del delta HIT en %s/%s (%s, %s)", sector_key, tier.value, clave,
                    periodo)
    else:
        if presupuesto_restante_s is not None and presupuesto_restante_s < MINIMO_PARA_NARRAR_S:
            return narratives, [_omitida(
                OMITIDA_TIEMPO,
                f"quedaban {presupuesto_restante_s:.0f} s del presupuesto de ensamblado y "
                f"narrar el delta necesita al menos {MINIMO_PARA_NARRAR_S:.0f}")]
        try:
            texto, omision = await _narrar(contexto, feeds[0], lang, presupuesto_restante_s)
        except Exception as e:  # noqa: BLE001
            logger.exception("narración del delta de %s falló; se omite", sector_key)
            texto, omision = None, _omitida(OMITIDA_DEGRADADA, f"el motor falló: {e}")
        if omision is not None or texto is None:
            omision = omision or _omitida(OMITIDA_DEGRADADA, "sin texto")
            logger.warning("Sección del delta de %s/%s OMITIDA (%s): %s", sector_key,
                           tier.value, omision["motivo"], omision["detalle"])
            if omision["motivo"] == OMITIDA_DEGRADADA:
                from shared.narrative.degradation_events import emit_narrative_degraded
                emit_narrative_degraded(surface="products", sector_key=sector_key,
                                        tier=tier.value, sections=[SECCION_DELTA],
                                        blocked=False, period=snapshot.period)
            return narratives, [omision]
        _escribir_cache(db, key, fp, texto)

    # LO VIVO, AL SERVIR: el encabezado con la fecha de la última descarga se antepone en
    # cada entrega y nunca se guarda. Y lo vetado de un feed se declara al pie aunque otro
    # se publique.
    encabezado = encabezado_del_movimiento(bloque, feeds)
    partes = [p for p in (encabezado, sin_lineas_de_atribucion(texto, feeds),
                          nota_de_los_no_publicables(bloque), pie_de_atribucion(feeds)) if p]
    return {**narratives, SECCION_DELTA: "\n\n".join(partes)}, []
