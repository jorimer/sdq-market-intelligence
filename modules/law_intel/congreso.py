"""Convierte una obligación cuyo cumplimiento es un ACTO DEL CONGRESO en un hecho con fecha.

Las siete obligaciones de la Ley 1-12 se reparten en dos familias. Las que consisten en dictar
una norma las computa `normativa.py` contra la Gaceta. Quedaban afuera las que consisten en
**constituir una comisión** (art. 51) o en **remitir un informe con el Proyecto de Presupuesto**
(art. 50): actos que no llegan a la Gaceta y cuyo rastro vive en los expedientes del propio
Congreso. Este módulo los busca ahí.

**La regla nueva que gobierna este módulo: el CONTROL POSITIVO.** La base normativa declara
hasta dónde su corpus está completo, y ese campo es lo único que autoriza a publicar «no se
dictó». El registro legislativo no declara nada: devuelve una lista, y una lista vacía puede
ser «no existe» o «esta consulta no busca lo que creés». No es una hipótesis — la búsqueda por
palabra clave del propio registro devuelve CERO para «bicameral» mientras el listado por tipo
devuelve cinco comisiones bicamerales. Por eso ninguna consulta de acá concluye una ausencia
sin que una consulta hermana, que DEBE traer resultados, los traiga.

**El alcance se computa, no se supone.** El listado de comisiones sirve solo el período
legislativo vigente: pasarle el período anterior devuelve el mismo conjunto. Así que cualquier
lectura de ausencia vale para el período en curso y **no dice nada sobre 2012-2020**, que es
cuando esta obligación venció. Publicarlo sin ese recorte sería acusar al Congreso con una
fuente que no puede ver los años en disputa — y el destinatario del informe ES el Congreso.

**Registral no es textual.** Los metadatos del expediente llegan por un canal verificado; los
PDF viven en un host con certificado autofirmado. Sabemos que un documento existe, cómo se
titula y cuándo se depositó; no leímos qué dice. Cuando el deber depende del CONTENIDO, el
veredicto es `solo_registral` y no un cumplimiento: es la misma línea que el emisor de la base
normativa traza entre `grada: registral` y `grada: texto`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("sdq.law_intel.congreso")

#: Veredictos que este módulo puede emitir. Los cuatro primeros son estados de
#: `obligaciones.ESTADOS`; los dos últimos NO lo son —hablan de nuestra capacidad de
#: comprobar, no de la conducta del obligado— y por eso nunca se persisten.
VEREDICTOS = {
    "cumplida": "el acto consta en el registro del Congreso",
    "parcial": "consta una parte del deber y falta otra, con evidencia de cuál es cuál",
    "sin_registro_publico": "no se encontró rastro, y el alcance NO permite afirmar que no ocurrió",
    "solo_registral": ("el documento consta en el expediente y su CONTENIDO no se pudo leer: "
                       "no se juzga si satisface el deber"),
    "no_verificable": "no se pudo consultar, o el control positivo falló; el estado queda intacto",
}

#: Tipos de comisión del registro. Se fijan acá para que el motor no dependa de que el
#: catálogo del emisor conserve el orden — y para poder nombrar el control positivo.
TIPO_BICAMERAL_PERMANENTE = 976
TIPO_BICAMERAL_ESPECIAL = 977

#: Palabras con las que un documento del expediente presupuestario nombraría la vinculación
#: con la Estrategia. Se aplican sobre el TÍTULO, que es lo único que llega por canal
#: verificado, y por eso no alcanzan para dar por cumplido el deber: nombran al candidato.
_SEÑAS_DE_VINCULACION = ("ESTRATEGIA NACIONAL DE DESARROLLO", "END 2030", " END ",
                         "VINCULACI", "METAS DE LA ESTRATEGIA")

_SEÑA_BICAMERAL = "BICAMERAL"


@dataclass(frozen=True)
class Comprobacion:
    obligacion: str
    veredicto: str
    evidencia: str
    #: Lo que el registro puede y no puede ver, COMPUTADO en esta misma consulta. Viaja
    #: siempre y no solo con las acusaciones: sin él, un `sin_registro_publico` se lee como
    #: «no ocurrió» y un `parcial` se lee como si cubriera los catorce años de la ley.
    alcance: Optional[Dict[str, Any]] = None
    hallazgos: Sequence[Dict[str, Any]] = ()

    @property
    def acusa(self) -> bool:
        return self.veredicto in ("parcial",)


def _titulo(doc: Dict[str, Any]) -> str:
    return " ".join(str(doc.get("descripcion") or "").split()).upper()


def _alcance(periodo: Optional[str], control: str, control_n: int,
             **extra: Any) -> Dict[str, Any]:
    """El alcance que este módulo puede afirmar, armado en un solo lugar.

    Se construye acá y no en cada rama porque ya sabemos cómo termina lo contrario: cinco
    salidas, una sola con procedencia. La diferencia con la base normativa es que allá el
    alcance lo declara el emisor y acá lo computamos nosotros — y por eso `vacio_es_concluyente`
    es SIEMPRE falso: ninguna consulta de este registro autoriza a afirmar que algo no ocurrió.
    """
    return {
        "corpus": "SIL Ciudadano · Cámara de Diputados",
        "periodo_legislativo_servido": periodo,
        "vacio_es_concluyente": False,
        "control_positivo": {"consulta": control, "resultados": control_n,
                             "vale": control_n > 0},
        "advertencia": ("El registro no declara hasta dónde está completo. Una lista vacía no "
                        "autoriza a afirmar que el acto no ocurrió, y menos en años que este "
                        "corpus no sirve."),
        **extra,
    }


def _periodo_servido(registros: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Qué período legislativo trae de verdad la respuesta, leído de los propios registros."""
    fechas = [str(r.get("fechaDesignacion") or "")[:4] for r in registros]
    años = sorted({f for f in fechas if f.isdigit()})
    if not años:
        return None
    return años[0] if len(años) == 1 else f"{años[0]}-{años[-1]}"


def comprobar_comision_bicameral(oid: str, listar_comisiones: Callable[[int], List[Dict]],
                                 documentos_de_presupuesto: Sequence[Dict[str, Any]] = (),
                                 ) -> Comprobacion:
    """¿Consta la Comisión Bicameral que el artículo 51 manda constituir?

    Dos preguntas distintas que el informe tiene que separar, porque el artículo pide una
    comisión PERMANENTE con seguimiento sistemático:

    1. ¿Hay una comisión bicameral permanente registrada? — el listado por tipo lo responde.
    2. ¿Actúa de hecho una comisión bicameral sobre el Presupuesto? — lo responden los
       documentos del expediente presupuestario, que es donde el acto deja rastro.

    Responder solo la primera fue el error que este módulo evita: el listado de permanentes
    está vacío y el expediente del Presupuesto trae informes de una comisión bicameral. Quien
    publicara «no consta comisión bicameral» sería refutado con el propio archivo del Congreso.
    """
    try:
        permanentes = list(listar_comisiones(TIPO_BICAMERAL_PERMANENTE))
        control = list(listar_comisiones(TIPO_BICAMERAL_ESPECIAL))
    except Exception as e:                       # el cliente levanta su propia excepción
        return Comprobacion(oid, "no_verificable",
                            f"No se pudo consultar el registro del Congreso: {e}")

    alcance = _alcance(_periodo_servido(permanentes + control),
                       "comisiones bicamerales especiales", len(control),
                       bicamerales_permanentes_registradas=len(permanentes))

    if not control and not permanentes:
        # El control positivo cayó: la consulta hermana, que sabemos que trae resultados,
        # tampoco trajo. No es una ausencia, es una consulta que no está funcionando.
        return Comprobacion(oid, "no_verificable",
                            "El control positivo no devolvió resultados: la consulta al "
                            "registro no está discriminando y su vacío no significa nada.",
                            alcance)

    actuaciones = [d for d in documentos_de_presupuesto if _SEÑA_BICAMERAL in _titulo(d)]

    if permanentes:
        nombres = ", ".join(str(c.get("comision", ""))[:80] for c in permanentes[:3])
        return Comprobacion(oid, "cumplida",
                            f"Consta comisión bicameral permanente en el registro: {nombres}.",
                            alcance, tuple(permanentes))

    if actuaciones:
        cita = "; ".join(f"«{_titulo(d)}»" for d in actuaciones[:4])
        return Comprobacion(
            oid, "parcial",
            "Una comisión bicameral SÍ examina el Presupuesto: el expediente presupuestario "
            f"registra {len(actuaciones)} documento(s) suyos ({cita}). Lo que NO consta en el "
            "registro consultado es una comisión bicameral PERMANENTE —la categoría existe en "
            "el catálogo del propio Congreso y está vacía—, que es lo que el artículo 51 pide "
            "para el seguimiento sistemático. Se designa por proyecto de presupuesto.",
            alcance, tuple(actuaciones))

    return Comprobacion(
        oid, "sin_registro_publico",
        "No se localizó comisión bicameral permanente ni actuación bicameral en el "
        "expediente presupuestario. No se afirma incumplimiento: el registro no declara su "
        "cobertura y sirve un solo período legislativo.", alcance)


_RX_PGE = re.compile(r"presupuesto general del estado para el a[ñn]o", re.I)


def presupuestos_anuales(iniciativas: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Los proyectos de Presupuesto General del Estado que remitió el Ejecutivo.

    Se filtra por tipo Y por origen: el registro devuelve también resoluciones internas que
    piden incluir obras en el Presupuesto, y contarlas como proyectos de presupuesto
    multiplicaría por diez el denominador del artículo 50.
    """
    return [i for i in iniciativas
            if str(i.get("tipo")) == "Proyecto de Ley"
            and str(i.get("origen")) == "Poder Ejecutivo"
            and _RX_PGE.search(str(i.get("descripcion") or ""))]


def comprobar_informe_de_vinculacion(oid: str, presupuestos: Sequence[Dict[str, Any]],
                                     documentos_de: Callable[[int], List[Dict]],
                                     ) -> Comprobacion:
    """¿Viaja con cada Proyecto de Presupuesto el informe de vinculación del artículo 50?

    El deber depende del CONTENIDO —un informe «que sustente su vinculación con las metas»—,
    y el contenido está del otro lado de un host con certificado autofirmado. Así que el
    veredicto máximo alcanzable por esta vía es `solo_registral`: consta qué se depositó y
    cuándo, no qué dice. Devolver `cumplida` porque el título suena parecido sería exactamente
    lo que este eje existe para no hacer.
    """
    if not presupuestos:
        return Comprobacion(oid, "no_verificable",
                            "El control positivo no devolvió resultados: no se localizó "
                            "ningún proyecto de Presupuesto en el registro, y sin ellos la "
                            "ausencia del informe no significa nada.",
                            _alcance(None, "proyectos de Presupuesto del Ejecutivo", 0))

    ciclos: List[Dict[str, Any]] = []
    for p in presupuestos:
        try:
            docs = list(documentos_de(int(p["id"])))
        except Exception as e:
            return Comprobacion(oid, "no_verificable",
                                f"No se pudo leer el expediente {p.get('numero')}: {e}")
        titulos = [_titulo(d) for d in docs]
        nombran = [t for t in titulos if any(s in t for s in _SEÑAS_DE_VINCULACION)]
        ciclos.append({"iniciativa": p.get("numero"), "depositado": str(p.get("fechaDeposito"))[:10],
                       "documentos": len(docs), "nombran_la_vinculacion": nombran,
                       "titulos": titulos})

    años = ", ".join(str(c["iniciativa"]) for c in ciclos)
    alcance = _alcance(_periodo_servido(presupuestos) or None,
                       "proyectos de Presupuesto del Ejecutivo", len(presupuestos),
                       ciclos_examinados=len(ciclos))

    con_seña = [c for c in ciclos if c["nombran_la_vinculacion"]]
    if len(con_seña) == len(ciclos):
        return Comprobacion(
            oid, "solo_registral",
            f"En los {len(ciclos)} proyectos de Presupuesto del registro ({años}) consta un "
            "documento cuyo título nombra la vinculación con la Estrategia. El título llega "
            "por canal verificado; el contenido no se pudo leer, así que no se juzga si "
            "sustenta la vinculación que el artículo exige.", alcance, tuple(ciclos))

    sin_seña = [c for c in ciclos if not c["nombran_la_vinculacion"]]
    faltan = ", ".join(str(c["iniciativa"]) for c in sin_seña)
    return Comprobacion(
        oid, "sin_registro_publico",
        f"En {len(sin_seña)} de los {len(ciclos)} proyectos de Presupuesto del registro "
        f"({faltan}) ningún documento del expediente nombra en su título la vinculación con "
        "la Estrategia. NO se afirma incumplimiento por dos motivos que hay que decir juntos: "
        "el informe pudo depositarse bajo otro título —el expediente trae un «informe "
        "explicativo» cuyo contenido no se pudo leer— y el registro solo sirve el período "
        "legislativo vigente, no los años en que esta obligación venció.", alcance,
        tuple(ciclos))
