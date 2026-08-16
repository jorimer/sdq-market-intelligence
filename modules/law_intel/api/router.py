"""Law Intel — API.

prefix: /api/v1/law-intel

Sirve el REGISTRO de un expediente: lo que la ley manda. No mide cumplimiento — el dato real
y el semáforo meta-vs-real llegan con los bindings. La separación es deliberada: permite
responder «¿cambió la meta o cambió el dato?», que es la pregunta que el artículo 20 de la
Ley 1-12 vuelve interesante al dejar que el propio evaluado mueva las metas por vía
administrativa.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from modules.law_intel.bindings import cargar_bindings, cobertura
from modules.law_intel.verificacion import informe
from modules.macro_monitor.models.models import MacroSeries
from modules.law_intel.obligaciones import ESTADOS as ESTADOS_OBLIGACION
from modules.law_intel.obligaciones import cargar_obligaciones
from modules.law_intel.obligaciones import resumen as resumen_obligaciones
from modules.law_intel.scoring.accionabilidad import CLASES, recomendaciones
from modules.law_intel.scoring.accionabilidad import resumen as resumen_accion
from modules.law_intel.ratificacion import (ESTADOS as ESTADOS_RATIFICACION,
                                            DerivaNoAutorizada, exigir_servible)
from modules.law_intel.ratificacion import estado as estado_ratificacion
from modules.law_intel.ratificacion import publicable as ratificacion_publicable
from modules.law_intel.registro import ESCALAS, Expediente, cargar, expedientes
from modules.law_intel.scoring.brecha import TIPOS, brechas, desbloqueo
from modules.law_intel.scoring.coherencia_proceso import VEREDICTOS as VEREDICTOS_COHERENCIA
from modules.law_intel.scoring.coherencia_proceso import resumen as resumen_coherencia
from modules.law_intel.scoring.coherencia_proceso import revisar
from modules.law_intel.scoring.brecha import resumen as resumen_brecha
from modules.law_intel.scoring.semaforo import VEREDICTOS, panel
from modules.law_intel.scoring.semaforo import resumen as resumen_semaforo
from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db

logger = logging.getLogger("sdq.law_intel.api")
router = APIRouter()


def _expediente(expediente_id: str) -> Expediente:
    try:
        exp = cargar(expediente_id)
    except Exception as exc:                       # noqa: BLE001 — se traduce a 404/500
        logger.warning("expediente no cargable: %s (%s)", expediente_id, exc)
        raise HTTPException(status_code=404, detail=f"Expediente no encontrado: {expediente_id}")
    # Puerta de ratificación: si las metas se movieron sin norma que lo autorice, el
    # expediente NO se sirve. Avisar y publicar igual sería tener el mismo defecto que el
    # informe denuncia — un registro que solo avisa de la deriva es un registro que deriva.
    try:
        exigir_servible(expediente_id)
    except DerivaNoAutorizada as exc:
        logger.error("deriva no autorizada en %s: %s", expediente_id, exc)
        raise HTTPException(status_code=409, detail=str(exc))
    return exp


@router.get("/instrumentos")
def listar_instrumentos(_: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Las leyes con expediente cargado."""
    filas = []
    for eid in expedientes():
        e = cargar(eid)
        filas.append({
            "id": e.id, "expediente": eid, "titulo": e.titulo, "norma": e.norma,
            "vigencia_hasta": e.meta.get("vigencia_hasta"),
            "indicadores": len(e.numerados), "filas_medibles": len(e.indicadores),
        })
    return {"instrumentos": filas}


@router.get("/{expediente_id}/indicadores")
def indicadores(expediente_id: str,
                eje: Optional[int] = Query(None, ge=1),
                incluir_subfilas: bool = Query(True),
                _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """El registro que fija la ley: línea base y metas por período.

    `admite_delta` viaja con cada fila para que ningún consumidor reste lo que no se resta:
    solo la escala numérica admite una diferencia meta-vs-real. Una banda PEFA se ordena, un
    umbral se cumple o no, y una meta redactada exige juicio.
    """
    e = _expediente(expediente_id)
    filas: List[Any] = e.indicadores if incluir_subfilas else e.numerados
    if eje is not None:
        # El eje válido lo declara el EXPEDIENTE, no una constante. La primera versión
        # validaba `le=4` — los cuatro ejes de la END— y un instrumento con cinco habría
        # recibido un 422 por una consulta legítima. Fue el único supuesto de la END que se
        # había filtrado fuera del expediente.
        declarados = set((e.meta.get("ejes") or {}))
        if declarados and eje not in declarados:
            raise HTTPException(
                status_code=404,
                detail=(f"El instrumento {e.id} no tiene eje {eje}; declara "
                        f"{sorted(declarados)}"))
        filas = [i for i in filas if i.eje == eje]
    return {
        "instrumento": {"id": e.id, "titulo": e.titulo, "norma": e.norma},
        "conteo": {
            "numerados": len([i for i in filas if not i.subfila_de]),
            "filas": len(filas),
            # El denominador de un eje cambia según se cuenten indicadores numerados o filas
            # medibles. Se publican los dos para que ninguna cifra derivada elija en silencio.
            "por_eje_declarado": e.meta.get("indicadores_por_eje"),
        },
        "indicadores": [{
            "id": i.id, "eje": i.eje, "indicador": i.nombre, "subfila_de": i.subfila_de,
            "escala": i.escala, "admite_delta": i.admite_delta,
            "base": {"anio": i.base_anio, "anio_texto": i.base_anio_texto, "valor": i.base_valor},
            "metas": i.metas,
            "anios_sin_meta_numerica": i.anios_sin_meta_numerica,
        } for i in filas],
    }


@router.get("/{expediente_id}/procedencia")
def procedencia(expediente_id: str, _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """De dónde sale el registro y qué fuentes admite el expediente.

    La procedencia se GENERA del expediente, nunca se redacta: es la misma regla que rige el
    resto de la plataforma. Y las fuentes admitidas se publican porque son lo que sostiene
    que el producto se venda a una parte interesada sin dejar de ser independiente.
    """
    e = _expediente(expediente_id)
    reg = e.meta.get("registro") or {}
    return {
        "instrumento": {"id": e.id, "titulo": e.titulo, "norma": e.norma,
                        "promulgada": e.meta.get("promulgada")},
        "registro": {
            "articulos": e.meta.get("articulos_indicadores"),
            "extraido_por": reg.get("extraido_por"),
            "metas_verificadas_a_mano": reg.get("metas_verificadas_a_mano"),
            "nota": reg.get("nota"),
        },
        "fuentes_admitidas": e.meta.get("fuentes_admitidas"),
        "escalas": ESCALAS,
    }


@router.get("/{expediente_id}/cobertura")
def cobertura_(expediente_id: str, _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """La cifra de portada: cuántos indicadores de la ley el informe realmente mide.

    Cuenta solo bindings VERIFICADOS. Un binding propuesto es una hipótesis sobre qué serie
    mide qué indicador; sumarlo a la cobertura sería afirmar haber medido lo que nadie
    comprobó, y esta cifra es la que el cliente usa para decidir si el informe le sirve.
    """
    _expediente(expediente_id)
    return cobertura(expediente_id)


@router.get("/{expediente_id}/semaforo")
def semaforo_(expediente_id: str,
              corte: str = Query(..., pattern=r"^\d{4}$"),
              _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Meta contra dato real al corte dado, sin eufemismo.

    Con cero bindings verificados el panel entero responde `sin_medicion`, y ese es el estado
    verdadero — no una falla del endpoint. Las observaciones entran cuando un binding pasa a
    verificado; hasta entonces el informe no puede afirmar cumplimiento de nada.
    """
    e = _expediente(expediente_id)
    bs = cargar_bindings(expediente_id)
    veredictos = panel(e.numerados, bs, {}, corte)
    return {
        "instrumento": {"id": e.id, "norma": e.norma}, "corte": corte,
        "cobertura": cobertura(expediente_id),
        "resumen": resumen_semaforo(veredictos),
        "veredictos": [{
            "indicador": v.indicador, "veredicto": v.veredicto, "cumple": v.cumple,
            "meta_periodo": v.meta_periodo, "meta": v.meta, "observado": v.observado,
            "periodo_observado": v.periodo_observado, "distancia": v.distancia,
            "trayectoria": v.trayectoria, "motivo": v.motivo,
        } for v in veredictos],
        "vocabulario": VEREDICTOS,
    }


@router.get("/{expediente_id}/brechas")
def brechas_(expediente_id: str, _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Lo que el informe no puede medir, de quién es cada hueco y qué desbloquea cerrarlo.

    `desbloqueo` es el mismo cómputo que la sugerencia interna de fuentes con otro
    destinatario: hacia adentro dice «conectar esto sube la cobertura»; hacia el cliente,
    «exigir que se publique esto sube la cobertura». En los dos casos la cifra es el delta.
    """
    e = _expediente(expediente_id)
    br = brechas(e.numerados, cargar_bindings(expediente_id))
    return {
        "instrumento": {"id": e.id, "norma": e.norma},
        "resumen": resumen_brecha(br, len(e.numerados)),
        "brechas": [{
            "indicador": b.indicador, "nombre": b.nombre, "eje": b.eje, "tipo": b.tipo,
            "responsable": b.responsable, "detalle": b.detalle,
            "serie_candidata": b.serie_candidata,
        } for b in br],
        "desbloqueo": desbloqueo(br),
        "tipos": TIPOS,
        # La frontera que mantiene vendible el producto como independiente.
        "alcance_de_la_recomendacion": (
            "Se recomienda la PUBLICACIÓN del dato, nunca la política. El informe señala qué "
            "falta y a quién la ley se lo asigna; no opina sobre qué debería hacer el Estado "
            "con el indicador."),
    }


@router.get("/{expediente_id}/obligaciones")
def obligaciones_(expediente_id: str, _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Qué manda la ley hacer, a quién, con qué plazo — y qué pasa si no.

    `frase_publicable` es la única forma en que cada estado puede decirse en un informe. La
    distinción que gobierna el módulo: `incumplida` afirma que algo no se hizo y exige
    evidencia; `sin_registro_publico` dice que no se encontró rastro y NO afirma
    incumplimiento. El destinatario del informe suele ser el órgano obligado, y una afirmación
    negativa sin comprobar es refutable con un solo documento.
    """
    e = _expediente(expediente_id)
    obs = cargar_obligaciones(expediente_id)
    return {
        "instrumento": {"id": e.id, "norma": e.norma},
        "resumen": resumen_obligaciones(expediente_id),
        "obligaciones": [{
            "id": o.id, "articulo": o.articulo, "deber": o.deber, "deudor": o.deudor,
            "estado": o.estado, "consecuencia": o.consecuencia, "plazo": o.plazo,
            "periodicidad": o.periodicidad, "evidencia": o.evidencia,
            "exigible": o.exigible, "produce": o.produce,
            "habilita_exigir": o.habilita_exigir,
            "verificacion_pendiente": o.requiere_verificacion_antes_de_publicar,
            "frase_publicable": o.frase_publicable(),
        } for o in obs],
        "estados": ESTADOS_OBLIGACION,
    }


@router.get("/{expediente_id}/recomendaciones")
def recomendaciones_(expediente_id: str, _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """La sección con la que cierra el informe: qué se puede accionar y qué rinde cada acción.

    Cada frase se ARMA de artículo, deber, deudor e instrumento tomados del registro: no hay
    campo de texto libre donde pudiera alojarse una opinión de política. Es lo que sostiene
    que el producto se venda a una parte interesada sin dejar de ser independiente.
    """
    e = _expediente(expediente_id)
    br = brechas(e.numerados, cargar_bindings(expediente_id))
    recs = recomendaciones(br, cargar_obligaciones(expediente_id))
    return {
        "instrumento": {"id": e.id, "norma": e.norma},
        "resumen": resumen_accion(recs),
        "recomendaciones": [{
            "clase": r.clase, "recomendacion": r.frase(), "base_legal": r.base_legal,
            "deudor": r.deudor, "instrumentos": r.instrumentos,
            "desbloquea_indicadores": r.desbloquea, "indicadores": r.indicadores,
            "estado_obligacion": r.estado_obligacion,
            "verificacion_pendiente": r.verificacion_pendiente,
        } for r in recs],
        "clases": CLASES,
    }


@router.get("/{expediente_id}/coherencia")
def coherencia_(expediente_id: str,
                corte: str = Query("2025", pattern=r"^\d{4}$"),
                _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """¿El proceso que se reporta cumplido movió el resultado?

    Cruza el cumplimiento formal de cada pacto contra los indicadores que existía para mover.
    Discrimina a propósito: un instrumento con bajo cumplimiento y mal resultado NO es una
    incoherencia — es algo que no se ejecutó, que es un hallazgo distinto. Y cero compromisos
    no es cumplimiento bajo: es ausencia de instrumento.
    """
    e = _expediente(expediente_id)
    hs = revisar(expediente_id, {i.id: i for i in e.indicadores}, corte)
    return {
        "instrumento": {"id": e.id, "norma": e.norma}, "corte": corte,
        "resumen": resumen_coherencia(hs),
        "hallazgos": [{
            "instrumento_de_proceso": h.instrumento, "indicador": h.indicador,
            "veredicto": h.veredicto, "lectura": h.frase(),
            "cumplimiento_proceso": h.cumplimiento_proceso,
            "base": h.base, "meta": h.meta, "observado": h.observado,
            "brecha_cerrada": h.brecha_cerrada,
        } for h in hs],
        "vocabulario": VEREDICTOS_COHERENCIA,
        "procedencia_de_las_observaciones": (
            "Instantáneas de documentos oficiales publicados y fechados, no series vivas. "
            "Cuando el binding del indicador esté verificado, el oráculo debe preferir la serie."),
    }


def _proveedor_mm_series(db: Session) -> Callable[[str], List[tuple]]:
    """Lee `mm_series` — el catálogo real de series de la plataforma.

    Vive acá y no en `verificacion.py` para que el motor no dependa de una tabla concreta:
    la comprobación recibe un proveedor y no sabe de dónde salen los datos, así que atar un
    expediente a otra fuente no obliga a tocarla.
    """
    def leer(codigo: str) -> List[tuple]:
        filas = (db.query(MacroSeries.period, MacroSeries.value)
                 .filter(MacroSeries.series_code == codigo,
                         MacroSeries.value.isnot(None))
                 .order_by(MacroSeries.period).all())
        return [(str(p), float(v)) for p, v in filas]
    return leer


@router.get("/{expediente_id}/bindings/verificacion")
def verificacion_(expediente_id: str,
                  corte: str = Query("2025", pattern=r"^\d{4}$"),
                  db: Session = Depends(get_db),
                  _: User = Depends(require_role(UserRole.analyst))) -> Dict[str, Any]:
    """Comprueba cada binding contra las series reales, en el entorno que las tiene.

    Devuelve qué bindings pueden pasar a `verificado` y cuánta cobertura gana el expediente
    si se promueven. **No muta nada**: el estado de un binding es un hecho comiteado y el YAML
    se actualiza por PR. Si la cobertura pudiera subir en caliente, la cifra de portada
    dejaría de ser verificable contra el repositorio.
    """
    _expediente(expediente_id)
    return informe(expediente_id, _proveedor_mm_series(db), corte)


@router.get("/{expediente_id}/ratificacion")
def ratificacion_(expediente_id: str, _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Estado del sello de las metas: aprobadas una vez, inmóviles sin norma que lo autorice.

    Un expediente en `deriva_no_autorizada` devuelve 409 en el resto de las rutas. Esta ruta
    lo sirve igual a propósito: es la que dice QUÉ se movió y contra qué sello, y bloquearla
    dejaría el diagnóstico fuera de alcance justo cuando hace falta.
    """
    if expediente_id not in expedientes():
        raise HTTPException(status_code=404, detail=f"Expediente no encontrado: {expediente_id}")
    st = estado_ratificacion(expediente_id)
    return {
        "expediente": st.expediente, "estado": st.estado, "servible": st.servible,
        "hash_metas_actual": st.hash_actual, "hash_metas_sellado": st.hash_sellado,
        "sellado_el": st.sellado_el, "sellado_por": st.sellado_por,
        "enmienda_vigente": (
            {"norma": st.enmienda_vigente.norma, "fecha": st.enmienda_vigente.fecha,
             "origen": st.enmienda_vigente.origen, "detalle": st.enmienda_vigente.detalle,
             "indicadores": st.enmienda_vigente.indicadores}
            if st.enmienda_vigente else None),
        "lectura_publicable": ratificacion_publicable(expediente_id),
        "estados": ESTADOS_RATIFICACION,
        "regla": ("Las metas se aprueban UNA VEZ. Cambiarlas exige una norma que lo autorice, "
                  "registrada como enmienda con su hash resultante: una norma real no puede "
                  "servir de paraguas a un cambio distinto del que autorizó."),
    }
