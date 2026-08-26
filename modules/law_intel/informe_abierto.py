"""El informe ABIERTO de una ley: el tercer entregable, y el único sin destinatario.

El producto emite hoy dos documentos con destinatario —el informe técnico y el dictamen—,
y los dos son confidenciales del cliente que los encarga. Éste es el tercero y es de otra
naturaleza: dice **qué ordena la norma, qué se mide de ella y de dónde sale cada cifra**, sin
publicar el veredicto de cumplimiento, que es lo que el cliente pagó.

**Por qué no es un nivel del producto y sí una superficie propia.** El primer intento fue
convertirlo en el Pulse. El contrato lo rechaza —«Pulse jamás nombra entidades», declarado no
negociable en `shared.products.tiers`— y el contrato tiene razón: el anonimato del Pulse
existe para que la vista abierta de un eje sectorial no filtre el nombre de un banco. Forzar
la excepción para las leyes habría abierto la puerta para todos.

Y al mirarlo de nuevo, el encaje estaba mal de origen: **los tres entregables no son tres
profundidades, son tres documentos.** Los niveles del producto miden cuánto se profundiza;
esto es otra pieza, con otra audiencia y otro registro. Va por su propia ruta.

**Casi todo el documento se COMPUTA.** Las tablas —obligaciones, cobertura, quién produce
cada cifra— salen del expediente y del registro. Eso lo vuelve reproducible y barato: no
depende de una generación de IA y dos lecturas del mismo día dan lo mismo salvo que el dato
haya cambiado.

**Registro EXTERNO.** Sin andamiaje de método: nada de «hallazgo crítico», severidades ni
rótulos internos. El lector está fuera de SDQ y ve la conclusión escrita en prosa, no el
método por su nombre. Lo vigila `test_informe_abierto.py`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.law_intel.informe_abierto")

#: Marca de agua. Dice lo contrario que la del dictamen a propósito: éste se comparte.
MARCA = "Documento abierto · SDQ Consulting Group"

#: Cómo se dice en prosa cada estado de una obligación. El vocabulario interno
#: —`sin_registro_publico`, `cumplida_tarde`— no sale del expediente: acá se traduce, porque
#: el lector externo no tiene por qué conocer nuestro esquema.
ESTADO_EN_PROSA = {
    "cumplida": "Realizada dentro del plazo",
    "cumplida_tarde": "Realizada fuera del plazo",
    "parcial": "Realizada en parte",
    "incumplida": "No realizada",
    "sin_registro_publico": "Sin registro público localizado",
    "pendiente_no_vencida": "Plazo aún no vencido",
    "no_exigible": "No exigible",
}

#: Y cómo se dice el tipo de deudor. «universo» es jerga nuestra; lo que el lector necesita
#: saber es que la obligación recae sobre cientos de instituciones y no sobre una.
DEUDOR_EN_PROSA = {
    "organo": "Un órgano determinado",
    "universo": "Todos los entes de la Administración",
    "indeterminado": "Sin deudor determinado",
}

#: La advertencia que acompaña SIEMPRE a la tabla de obligaciones. No es un descargo de
#: cortesía: «no se encontró registro» y «no se hizo» son afirmaciones distintas, y publicar
#: la segunda con la evidencia de la primera es lo que vuelve refutable un informe entero.
ADVERTENCIA_DEL_REGISTRO = (
    "«Sin registro público localizado» no afirma un incumplimiento: significa que no se "
    "encontró constancia pública de que la obligación se haya atendido, y esa es una "
    "afirmación sobre la evidencia disponible, no sobre la conducta del obligado. Varias de "
    "estas obligaciones recaen sobre el conjunto de la Administración; establecer si se "
    "atendieron exige revisarlas institución por institución.")

#: Qué operación del console alimenta cada serie de seguimiento declarada por un expediente.
#:
#: **Explícito, y no por coincidencia de cadenas.** El primer intento buscaba el nombre de la
#: serie dentro de la descripción de la operación: funciona hasta que alguien reescribe la
#: descripción, y entonces el informe deja de prometer actualización sin que nadie se entere
#: — un fallo silencioso en la sección que existe para decirle al lector cuándo volver.
#:
#: Es un mapa a mano, y por eso lleva guard: `test_informe_abierto` exige que TODA
#: `serie_de_seguimiento` declarada en cualquier expediente tenga su entrada acá, y que la
#: operación exista de verdad en el registro.
OPERACION_QUE_ALIMENTA = {
    "social_dev:tramites_catalogados": "tramites-registro-unico",
    "social_dev:tramites_con_tiempo_declarado": "tramites-registro-unico",
    "social_dev:tramites_pct_con_tiempo_sobre_los_catalogados": "tramites-registro-unico",
}

_MAX_FILAS_INDICADORES = 60


def _tabla_de_obligaciones(publicable: Dict[str, Any]) -> Optional[Tuple[str, List[List[str]]]]:
    obs = publicable.get("obligaciones") or []
    if not obs:
        return None
    filas: List[List[str]] = [["Artículo", "Qué ordena", "A quién", "Estado", "Consecuencia"]]
    for o in sorted(obs, key=lambda x: int(x.get("articulo") or 0)):
        filas.append([
            str(o.get("articulo") or "—"),
            # Se corta en el último espacio, no a media palabra: esta celda se imprime.
            _recortar(str(o.get("deber") or ""), 74),
            DEUDOR_EN_PROSA.get(str((o.get("deudor") or {}).get("tipo") or ""), "—"),
            ESTADO_EN_PROSA.get(str(o.get("estado")), str(o.get("estado"))),
            "Sí" if o.get("consecuencia") else "No",
        ])
    return ("Qué ordena la norma", filas)


def _recortar(texto: str, limite: int) -> str:
    """Corta en el último espacio antes del límite.

    Un corte a media palabra —«dentro de quinc», «vigencia d»— se imprime tal cual en la
    tabla, y en un documento que se comparte eso dice que nadie lo miró antes de soltarlo.
    """
    t = " ".join(texto.split())
    if len(t) <= limite:
        return t
    return t[:limite].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _tabla_de_medicion(verificabilidad: Dict[str, Any]) -> Optional[Tuple[str, List[List[str]]]]:
    """Qué se mide de la ley y quién produce cada cifra.

    Es la mitad del valor del documento: la otra mitad es la tabla de obligaciones. Un
    inventario que dice «medimos 46» sin decir de dónde sale cada uno no se puede comprobar,
    y un inventario que no se puede comprobar no sirve para lo que este documento existe.
    """
    cadena = verificabilidad.get("cadena_por_sujeto")
    if not isinstance(cadena, list):
        return None
    inds = [c for c in cadena if isinstance(c, dict) and c.get("clase") == "indicador"]
    if not inds:
        return None
    filas: List[List[str]] = [["Indicador", "Qué mide", "Quién produce el dato"]]
    for c in inds[:_MAX_FILAS_INDICADORES]:
        filas.append([str(c.get("sujeto") or "—"),
                      _recortar(str(c.get("nombre") or ""), 58),
                      _recortar(str(c.get("productor") or ""), 58)])
    if len(inds) > _MAX_FILAS_INDICADORES:
        # El truncado se DECLARA. Una tabla cortada en silencio se lee como el inventario
        # completo, y eso convierte una omisión de formato en una cifra falsa.
        filas.append(["…", f"y {len(inds) - _MAX_FILAS_INDICADORES} indicadores más", ""])
    return ("Qué se mide, y quién produce cada cifra", filas)


def _tabla_de_cobertura(cobertura: Dict[str, Any],
                        campo: Dict[str, Any]) -> Tuple[str, List[List[str]]]:
    return ("Alcance de la medición", [
        ["Concepto", "Valor"],
        ["Indicadores que la norma numera", str(cobertura.get("total", "—"))],
        ["Con fuente verificada", str(cobertura.get("medidos", "—"))],
        ["Sin medición, con motivo registrado",
         str(campo.get("declarados_sin_veredicto", "—"))],
        ["Sin motivo registrado", str(campo.get("en_silencio", "—"))],
    ])


#: Cuántas instituciones entran en la tabla. Con 91 la tabla ocupa tres páginas y deja de
#: leerse; con las diez más consultadas se ve quién concentra la espera de la gente.
_TOP_INSTITUCIONES = 12


def _mil(n: Any) -> str:
    """Notación española de miles. El informe entero usa una sola convención."""
    return f"{int(n or 0):,}".replace(",", ".")


def _por_sujeto(db: Any, tema: str, periodo: str) -> Dict[str, float]:
    from modules.social_dev.models.models import SocialIndicator
    filas = (db.query(SocialIndicator)
             .filter(SocialIndicator.theme == tema, SocialIndicator.period == periodo).all())
    return {str(f.entity_key): float(f.value or 0) for f in filas}


def _tiempos_declarados(db: Any, periodo: str) -> Dict[str, Tuple[float, str]]:
    """`{slug: (días, «texto · nivel»)}` de los trámites que declaran su tiempo."""
    from modules.social_dev.models.models import SocialIndicator
    from modules.social_dev.tramites_sync import TEMA_TIEMPO_POR_TRAMITE
    filas = (db.query(SocialIndicator)
             .filter(SocialIndicator.theme == TEMA_TIEMPO_POR_TRAMITE,
                     SocialIndicator.period == periodo).all())
    return {str(f.entity_key): (float(f.value or 0), str(f.disaggregation or ""))
            for f in filas}


def _instituciones_que_declaran(db: Any, periodo: str) -> set:
    """Siglas con al menos un trámite de tiempo declarado, leído del desglose persistido.

    El primer intento tenía una caché que nunca se llenaba: la columna habría dicho «No»
    para todas, afirmando que ninguna institución declara nada. El sync persiste el conteo
    por institución justamente porque el slug del trámite no lleva la sigla.
    """
    from modules.social_dev.tramites_sync import TEMA_CON_TIEMPO_POR_INSTITUCION
    return {s for s, n in _por_sujeto(db, TEMA_CON_TIEMPO_POR_INSTITUCION, periodo).items()
            if n > 0}


def _anexo_tramites(db: Any) -> List[Tuple[str, List[List[str]]]]:
    """La evidencia del catálogo de trámites: la prueba de la obligación del artículo 39.

    Se lee de la SERIE persistida, no del portal. Un informe que sale del console no puede
    dispararle 711 llamadas a un emisor público cada vez que alguien lo descarga: la serie ya
    la tiene la operación mensual, y usarla mantiene el documento reproducible —dos descargas
    del mismo día dan lo mismo— y barato.
    """
    from modules.social_dev.models.models import SocialIndicator
    from modules.social_dev.tramites_sync import (ENTIDAD, TEMA_CON_TIEMPO,
                                                  TEMA_CONSULTAS_POR_INSTITUCION, TEMA_PCT,
                                                  TEMA_POR_INSTITUCION, TEMA_TOTAL)

    if db is None:
        return []
    filas = (db.query(SocialIndicator)
             .filter(SocialIndicator.entity_key == ENTIDAD,
                     SocialIndicator.theme.in_((TEMA_TOTAL, TEMA_CON_TIEMPO, TEMA_PCT)))
             .all())
    if not filas:
        return []
    # El período MÁS RECIENTE, y se nombra en el título: una tabla sin fecha de lectura
    # sobre un catálogo vivo se lee como si fuera de hoy para siempre.
    periodo = max(str(f.period) for f in filas)
    v = {f.theme: f.value for f in filas if str(f.period) == periodo}
    if TEMA_TOTAL not in v:
        return []
    tablas: List[Tuple[str, List[List[str]]]] = [(
        f"El catálogo de trámites al {periodo}", [
            ["Concepto", "Valor"],
            ["Trámites publicados en el catálogo", _mil(v[TEMA_TOTAL])],
            ["Instituciones que publican", str(len(_por_sujeto(db, TEMA_POR_INSTITUCION,
                                                              periodo)))],
            ["Consultas ciudadanas acumuladas",
             _mil(sum(_por_sujeto(db, TEMA_CONSULTAS_POR_INSTITUCION, periodo).values()))],
            ["Declaran su tiempo de respuesta", str(int(v.get(TEMA_CON_TIEMPO, 0)))],
            ["Proporción sobre los publicados", f"{v.get(TEMA_PCT, 0)} %".replace(".", ",")],
        ])]

    # Las que más ciudadanos consultan, con cuántos trámites publican y si alguno declara su
    # tiempo. Ordenadas por CONSULTAS y no por número de trámites: una institución con 61
    # trámites y otra con 1,5 millones de consultas no pesan igual para quien espera.
    consultas = _por_sujeto(db, TEMA_CONSULTAS_POR_INSTITUCION, periodo)
    cantidad = _por_sujeto(db, TEMA_POR_INSTITUCION, periodo)
    declaran = _instituciones_que_declaran(db, periodo)
    if consultas:
        filas = [["Institución", "Trámites", "Consultas", "Declara algún tiempo"]]
        for sigla, n in sorted(consultas.items(), key=lambda kv: -kv[1])[:_TOP_INSTITUCIONES]:
            filas.append([sigla, str(int(cantidad.get(sigla, 0))), _mil(n),
                          "Sí" if sigla in declaran else "No"])
        tablas.append(("Las instituciones más consultadas", filas))

    # Y los que sí lo declaran, AGRUPADOS por institución y plazo. Sin agrupar salen catorce
    # filas de pasaporte con el mismo tiempo, que ocupan media página y no dicen nada más que
    # la primera.
    tiempos = _tiempos_declarados(db, periodo)
    if tiempos:
        grupos: Dict[Tuple[str, str, str], int] = {}
        for _slug, (_dias, nota) in tiempos.items():
            partes = [x.strip() for x in nota.split("·")]
            if len(partes) < 3:
                continue
            grupos[(partes[0], partes[1], partes[2])] = grupos.get(
                (partes[0], partes[1], partes[2]), 0) + 1
        filas = [["Institución", "Trámites", "Tiempo que declara la ficha", "Cómo lo dice"]]
        for (sigla, texto, nivel), n in sorted(grupos.items(), key=lambda kv: (-kv[1], kv[0])):
            filas.append([sigla, str(n), texto,
                          "Nombra el campo" if nivel == "explicito" else "Lo dice en prosa"])
        # El numerador sale de la SUMA de las filas, no de `len(tiempos)`: una fila con la
        # nota malformada se salta arriba, y un título que la contara igual afirmaría un
        # total que la tabla debajo no muestra.
        tablas.append((f"Los trámites que declaran cuánto tardan ({sum(grupos.values())} de "
                       f"{_mil(v[TEMA_TOTAL])})", filas))
    return tablas


#: Anexos de evidencia propios de una ley. Se declaran por expediente y no se deducen: la
#: 167-21 tiene una serie que la sigue y las otras no, y un renderizador que adivinara cuál
#: aplicar acabaría poniéndole a una ley la evidencia de otra.
ANEXOS_POR_EXPEDIENTE = {
    "ley_167_21": _anexo_tramites,
}


def _entero(v: Any) -> int:
    """Un conteo de un resumen, como entero. Los resúmenes se tipan `Dict[str, object]` y de
    ahí no sale ni aritmética ni concordancia comprobables."""
    return int(v) if isinstance(v, (int, float)) else 0


def _plural(n: int, singular: str, plural: str, cero: Optional[str] = None) -> str:
    """Concordancia de número para la prosa del informe.

    «De los 1 indicadores… Los 1 restantes» es lo que sale de interpolar un contador en una
    frase escrita en plural. Se imprime en un documento que se comparte, y le dice al lector
    que nadie lo leyó antes de soltarlo.
    """
    if n == 0 and cero:
        return cero
    return singular if n == 1 else plural


def _prosa_de_declaraciones(dec: Dict[str, Any]) -> str:
    """Lo que el evaluado dijo sobre sus propios datos, en prosa y con su fecha.

    Cada una va con la consecuencia que tiene para lo que se mide. Citar lo que dijo el
    emisor sin decir qué implica deja al lector con una noticia, no con información.
    """
    partes = [
        "Los organismos evaluados han hecho declaraciones sobre la información que manejan. "
        "Se recogen porque cambian lo que puede afirmarse: «no hay dato» y «el organismo "
        "tiene el dato y declaró que no lo publica todavía» son cosas distintas."]
    for d in dec["declaraciones"]:
        cola = (f" El propio organismo indicó su disponibilidad a partir del "
                f"{d['disponible_desde']}." if d.get("disponible_desde") else
                " No se declaró una fecha a partir de la cual esté disponible.")
        partes.append(f"**{d['quien']}, {d['fecha']}.** {' '.join(d['que_declara'].split())}"
                      f"{cola} {' '.join(d['consecuencia_para_la_medicion'].split())}")
    return "\n\n".join(partes)


def _cuando_se_actualiza(expediente_id: str, db: Any) -> Optional[str]:
    """Cuándo vuelve a leerse el dato, tomado de la AGENDA de la operación que lo lee.

    No de una frase escrita a mano. Una promesa de actualización redactada en el documento
    envejece en cuanto alguien cambia la cadencia, y el lector no tiene cómo enterarse; la
    agenda es la que manda de verdad y es la que se publica.

    Se resuelve por la `serie_de_seguimiento` que la obligación declara: si ninguna
    obligación de esta ley sigue una serie, el documento no promete ninguna actualización.
    """
    from modules.law_intel.obligaciones import cargar_obligaciones

    series = {o.serie_de_seguimiento for o in cargar_obligaciones(expediente_id)
              if o.serie_de_seguimiento}
    if not series or db is None:
        return None
    try:
        from shared.operations.models import OperationSchedule
    except Exception:                                      # pragma: no cover - defensivo
        return None
    nombres = [OPERACION_QUE_ALIMENTA[x] for x in series if x in OPERACION_QUE_ALIMENTA]
    if not nombres:
        logger.info("[informe_abierto] %s sigue %s y ninguna operación la declara alimentar",
                    expediente_id, sorted(series))
        return None
    filas = (db.query(OperationSchedule)
             .filter(OperationSchedule.operation.in_(nombres)).all())
    activas = [f for f in filas if f.enabled and f.interval_hours]
    if not activas:
        return None
    f = min(activas, key=lambda x: x.interval_hours)
    dias = round(f.interval_hours / 24)
    proxima = f.next_run_at.date().isoformat() if f.next_run_at else None
    ultima = f.last_run_at.date().isoformat() if f.last_run_at else None
    partes = [f"El dato de este informe se vuelve a leer cada {dias} días."]
    if ultima:
        partes.append(f"La última lectura registrada es del {ultima}.")
    if proxima:
        partes.append(f"La próxima está prevista para el {proxima}.")
    partes.append(
        "La cadencia sale de la agenda del sistema que hace la lectura, no de una promesa "
        "escrita en este documento: si cambia, cambia acá.")
    return " ".join(partes)


def construir(expediente_id: str, db: Any = None) -> Dict[str, Any]:
    """Las secciones y las tablas del informe abierto de una ley.

    Devuelve la materia prima; el render es de quien llame. Separarlos deja probar el
    contenido sin generar un PDF, que es donde vive la mayor parte de lo que puede salir mal.
    """
    from modules.law_intel.bindings import cobertura as _cobertura
    from modules.law_intel.campo import resumen as _campo
    from modules.law_intel.obligaciones import cargar_obligaciones
    from modules.law_intel.obligaciones import resumen as _resumen_obligaciones
    from modules.law_intel.registro import cargar
    from modules.law_intel.declaraciones import publicable as _declaraciones
    from modules.law_intel.verificabilidad import publicable as _verificabilidad

    exp = cargar(expediente_id)
    cob = _cobertura(expediente_id)
    campo = _campo(expediente_id)
    obs: Dict[str, Any] = {
           "resumen": _resumen_obligaciones(expediente_id),
           "obligaciones": [
               {"articulo": o.articulo, "deber": o.deber, "deudor": o.deudor,
                "estado": o.estado, "consecuencia": o.consecuencia}
               for o in cargar_obligaciones(expediente_id)]}
    ver = _verificabilidad(expediente_id)
    dec = _declaraciones(expediente_id)

    tablas: List[Tuple[str, Sequence[Sequence[str]]]] = [_tabla_de_cobertura(cob, campo)]
    for t in (_tabla_de_obligaciones(obs), _tabla_de_medicion(ver)):
        if t is not None:
            tablas.append(t)
    anexo = ANEXOS_POR_EXPEDIENTE.get(expediente_id)
    if anexo is not None:
        tablas.extend(anexo(db))

    _actualiza = _cuando_se_actualiza(expediente_id, db)
    resumen_obs: Dict[str, Any] = obs.get("resumen") or {}
    lista_obs: List[Dict[str, Any]] = list(obs.get("obligaciones") or [])
    con_consecuencia = sum(1 for o in lista_obs if o.get("consecuencia"))
    # Enteros explícitos: los resúmenes se tipan como `Dict[str, object]` y de ahí no sale
    # una concordancia comprobable — ni aritmética.
    medidos = _entero(cob.get("medidos"))
    total = _entero(cob.get("total"))
    sin_medicion = _entero(campo.get("declarados_sin_veredicto"))

    secciones = {
        "que_es": (
            f"La {exp.norma} —{exp.titulo}— fija obligaciones a cargo de la Administración "
            f"Pública, y en algunos casos indicadores con metas. Este documento consigna qué "
            f"ordena, qué puede medirse hoy de su cumplimiento y de dónde sale cada cifra. Se "
            f"comparte abierto porque un inventario de fuentes vale más cuando otros pueden "
            f"usarlo y corregirlo.\n\n"
            f"No emite juicio sobre el cumplimiento de las metas. Ese análisis se prepara por "
            f"encargo y no se publica."),
        "lo_que_ordena": (
            f"El instrumento contiene {resumen_obs.get('total', 0)} obligaciones con deudor y "
            f"plazo identificables. La tabla siguiente consigna su estado.\n\n"
            f"{con_consecuencia} de ellas tienen una consecuencia jurídica asignada a su "
            f"incumplimiento. El resto no: la norma manda hacer algo y no dice qué ocurre si "
            f"no se hace.\n\n{ADVERTENCIA_DEL_REGISTRO}"),
        "lo_que_se_mide": (
            _plural(total,
                    "La norma numera un solo indicador y "
                    + ("cuenta hoy con fuente verificada. " if medidos
                       else "no cuenta hoy con fuente verificada. "),
                    f"De los {total} indicadores que la norma numera, {medidos} "
                    f"{_plural(medidos, 'cuenta', 'cuentan')} hoy con una fuente "
                    f"verificada. ")
            + _plural(sin_medicion,
                      "El indicador sin medición tiene un motivo registrado.",
                      f"Los {sin_medicion} restantes tienen un "
                      f"motivo registrado y ninguno queda sin explicación.",
                      cero="Ninguno queda sin explicación.")
            + "\n\n"
            "Una serie se admite como medición de un indicador cuando reproduce, en el año "
            "que la norma señala, el valor que la norma fija como línea base. Una "
            "coincidencia de nombre sin coincidencia de valor no identifica la magnitud, y "
            "una coincidencia de valor sin coincidencia de concepto tampoco."),
        **({"lo_que_declara_el_emisor": _prosa_de_declaraciones(dec)} if dec["total"] else {}),
        **({"cuando_se_actualiza": _actualiza} if _actualiza else {}),
        "alcance": (
            "Este documento no audita la exactitud de las cifras que publican los organismos "
            "citados ni verifica su conformidad con las metodologías que dichos organismos "
            "declaran. La identificación de un productor no constituye validación de sus "
            "cifras.\n\n"
            "Los valores corresponden al último período publicado a la fecha de emisión y "
            "pueden ser objeto de revisión por sus productores. El inventario se actualiza de "
            "forma continua.\n\n"
            "Las observaciones —una fuente que falte, una atribución que corregir— son "
            "bienvenidas y se incorporan con crédito: info@sdqconsulting.com.do"),
    }
    return {
        "expediente": expediente_id,
        "titulo": f"{exp.titulo} ({exp.norma})",
        "secciones": secciones,
        "tablas": tablas,
        "titulares": {"medidos": medidos, "total": total,
                      "obligaciones": resumen_obs.get("total", 0)},
    }


SECCIONES_EN_ORDEN = ("que_es", "lo_que_ordena", "lo_que_se_mide",
                      "lo_que_declara_el_emisor", "cuando_se_actualiza", "alcance")

TITULOS = {
    "que_es": "Qué es este documento",
    "lo_que_ordena": "Qué ordena la norma",
    "lo_que_se_mide": "Qué se mide, y cómo se verifica",
    "lo_que_declara_el_emisor": "Qué declara el organismo sobre su propia información",
    "cuando_se_actualiza": "Cuándo se actualiza este informe",
    "alcance": "Alcance y limitaciones",
}


def _titular(t: Dict[str, int]) -> str:
    """La cifra de portada, elegida por lo que la norma ES.

    «Mide 0 de 1 indicadores» es cierto y se lee como un fracaso, cuando lo que pasa es que
    la Ley 167-21 no es una ley de metas: son obligaciones. Titular por indicadores a una
    norma que casi no tiene le pone al documento una vara que su objeto no admite.
    """
    medidos, total, obs = t["medidos"], t["total"], t["obligaciones"]
    if medidos:
        return f"Mide {medidos} de {total} indicadores"
    if obs:
        return _plural(obs, "1 obligación con deudor y plazo",
                       f"{obs} obligaciones con deudor y plazo")
    return _plural(total, "1 indicador numerado", f"{total} indicadores numerados")


def render(expediente_id: str, db: Any = None, fmt: str = "pdf",
           output_dir: Optional[str] = None) -> str:
    """Genera el archivo del informe abierto y devuelve su ruta."""
    from shared.products.render import render_product_pdf

    d = construir(expediente_id, db)
    t = d["titulares"]
    return render_product_pdf(
        sector_key="law", display_name="SDQ Evaluación de Leyes",
        title=d["titulo"],
        period="",
        narratives={k: d["secciones"][k] for k in SECCIONES_EN_ORDEN if k in d["secciones"]},
        section_titles=TITULOS,
        tables=d["tablas"], charts=[],
        headline=_titular(t),
        subtitle="Documento abierto — qué ordena la norma y qué puede medirse de ella",
        watermark=MARCA, sample=False, output_dir=output_dir, fmt=fmt)
