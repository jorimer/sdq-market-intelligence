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

    tablas: List[Tuple[str, Sequence[Sequence[str]]]] = [_tabla_de_cobertura(cob, campo)]
    for t in (_tabla_de_obligaciones(obs), _tabla_de_medicion(ver)):
        if t is not None:
            tablas.append(t)

    resumen_obs: Dict[str, Any] = obs.get("resumen") or {}
    lista_obs: List[Dict[str, Any]] = list(obs.get("obligaciones") or [])
    con_consecuencia = sum(1 for o in lista_obs if o.get("consecuencia"))
    medidos = cob.get("medidos") or 0
    total = cob.get("total") or 0

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
            f"De los {total} indicadores que la norma numera, {medidos} cuentan hoy con una "
            f"fuente verificada. Los {campo.get('declarados_sin_veredicto', 0)} restantes "
            f"tienen un motivo registrado y ninguno queda sin explicación.\n\n"
            f"Una serie se admite como medición de un indicador cuando reproduce, en el año "
            f"que la norma señala, el valor que la norma fija como línea base. Una "
            f"coincidencia de nombre sin coincidencia de valor no identifica la magnitud, y "
            f"una coincidencia de valor sin coincidencia de concepto tampoco."),
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


SECCIONES_EN_ORDEN = ("que_es", "lo_que_ordena", "lo_que_se_mide", "alcance")

TITULOS = {
    "que_es": "Qué es este documento",
    "lo_que_ordena": "Qué ordena la norma",
    "lo_que_se_mide": "Qué se mide, y cómo se verifica",
    "alcance": "Alcance y limitaciones",
}


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
        headline=(f"Mide {t['medidos']} de {t['total']} indicadores"
                  if t["total"] else f"{t['obligaciones']} obligaciones registradas"),
        subtitle="Documento abierto — qué ordena la norma y qué puede medirse de ella",
        watermark=MARCA, sample=False, output_dir=output_dir, fmt=fmt)
