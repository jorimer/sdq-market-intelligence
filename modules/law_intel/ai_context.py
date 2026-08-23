"""Contexto que recibe el modelo para redactar la evaluación de una ley.

**Todo lo que es una RELACIÓN llega resuelto.** El veredicto de cada indicador, la dirección
de mejora, la fracción de brecha cerrada y la contradicción proceso-resultado se computan en
código y el modelo los COPIA. Es la doctrina de la plataforma y acá pesa más que en otros
motores: el informe oficial de la END llama «avance moderado» a lo que su propia definición
describe como *no se alcanzará la meta*, y este producto existe para no repetir ese giro. Si
el modelo tuviera que derivar el veredicto de una meta y un dato, lo derivaría con el mismo
tono amable.

**Cada clave nombra su población.** `cobertura_indicadores_medidos_sobre_90` y no
`cobertura_pct`: el registro tiene dos denominadores legítimos —90 indicadores numerados y
135 filas medibles— y una clave sin sujeto deja que el modelo elija el que suene mejor.

**La brecha y la recomendación son parte del contexto, no un apéndice.** El informe cierra
con lo que no se pudo medir y con qué se puede exigir; si eso no llega al modelo, la sección
sale redactada de memoria.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from modules.law_intel.bindings import cargar_bindings, cobertura
from modules.law_intel.campo import resumen as resumen_del_campo
from modules.law_intel.obligaciones import cargar_obligaciones
from modules.law_intel.obligaciones import resumen as resumen_obligaciones
from modules.law_intel.ratificacion import publicable as ratificacion_publicable
from modules.law_intel.registro import cargar
from modules.law_intel.scoring.accionabilidad import recomendaciones
from modules.law_intel.scoring.brecha import brechas
from modules.law_intel.scoring.brecha import resumen as resumen_brecha
from modules.law_intel.scoring.coherencia_proceso import revisar
from modules.law_intel.scoring.semaforo import panel
from modules.law_intel.scoring.semaforo import resumen as resumen_semaforo
from modules.law_intel.verificabilidad import publicable as verificabilidad_publicable

#: Glosa de `estancada` para el modelo. Es la distinción más fácil de perder al redactar:
#: «estancada» y «retrocede» suenan igual de mal y significan cosas distintas, y el informe
#: que llama retroceso a una serie plana es refutable con la fila de al lado.
GLOSA_ESTANCADA = (
    "El indicador NO se mueve. No escribas «retrocede» ni «se aleja»: la serie es plana y "
    "el lector puede comprobarlo en la misma tabla. Tampoco lo suavices a «se mantiene» a "
    "secas — la meta sí avanza con los años, así que quedarse quieto ensancha la brecha."
)


def salvedades_obligatorias(expediente_id: str) -> List[Dict[str, str]]:
    """Los indicadores medidos cuya verificación NO pasó por la línea base de la ley.

    Se computa del estado de cada binding y no de una lista escrita a mano: una lista a mano
    envejece en cuanto alguien promueve el siguiente, y el que falte es justo el que se
    publicaría sin salvedad.
    """
    return [{"indicador": b.indicador, "camino": b.verificado_por,
             "termino_del_emisor": b.termino_del_emisor or "",
             "salvedad": (b.nota or "").strip()}
            for b in sorted(cargar_bindings(expediente_id).values(), key=lambda x: x.indicador)
            if b.cuenta and b.verificado_por != "oraculo"]


def atribuciones_obligatorias(expediente_id: str) -> List[Dict[str, str]]:
    """Los indicadores medidos cuya FUENTE exige que se la nombre al publicar.

    Se computa cruzando los bindings con la lista blanca del instrumento, no de una lista a
    mano: la obligación es de la fuente y alcanza a todo indicador que la use, incluido el que
    alguien ate mañana. Una atribución que depende de que el redactor se acuerde es una
    atribución que se pierde en la primera reescritura.
    """
    exp = cargar(expediente_id)
    exigen = {f["id"]: f for f in (exp.meta.get("fuentes_admitidas") or [])
              if f.get("exige_atribucion")}
    return [{"indicador": b.indicador, "fuente": b.fuente,
             "atribucion": str(exigen[b.fuente].get("atribucion") or "").strip()}
            for b in sorted(cargar_bindings(expediente_id).values(), key=lambda x: x.indicador)
            if b.cuenta and b.fuente in exigen]


def law_ai_context(expediente_id: str, corte: str,
                   series: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    numerados = exp.numerados
    veredictos = panel(numerados, bs, series or {}, corte)
    br = brechas(numerados, bs)
    obs = cargar_obligaciones(expediente_id)
    recs = recomendaciones(br, obs)
    coh = revisar(expediente_id, {i.id: i for i in exp.indicadores}, corte)
    cob = cobertura(expediente_id)

    return {
        "instrumento": {
            "titulo": exp.titulo, "norma": exp.norma,
            "vigencia_hasta": exp.meta.get("vigencia_hasta"),
            "corte_evaluado": corte,
        },
        # ── Estado del sello de las metas ──
        # Si una norma movió la vara, el informe tiene que decirlo ANTES de juzgar
        # cumplimiento: un veredicto contra metas enmendadas y otro contra las originales son
        # lecturas distintas, y el lector tiene derecho a saber cuál está leyendo.
        "ratificacion_de_las_metas": ratificacion_publicable(expediente_id),
        "regla_de_la_vara": (
            "Si `ratificacion_de_las_metas` trae una enmienda de origen 'administrativa', "
            "decilo: significa que la vara la movió el propio evaluado bajo una potestad "
            "delegada, no el Congreso. No lo presentes como un cambio normativo cualquiera."),
        # ── Cobertura: la cifra de portada, con su denominador en la propia clave ──
        "cobertura_indicadores_medidos_sobre_total_de_la_ley": {
            "medidos": cob["medidos"], "total_indicadores_numerados": cob["total"],
            "pct": cob["pct"], "propuestos_sin_verificar": cob["propuestos_sin_verificar"],
            # La cobertura se abre por CAMINO. Publicarla como una sola cifra sería publicar
            # un número sobre dos poblaciones: unas reproducen la línea base que el
            # legislador escribió y otras no pudieron ni intentarlo.
            "medidos_por_camino_de_verificacion": cob["medidos_por_camino_de_verificacion"],
            "que_significa_cada_camino": cob["que_significa_cada_camino"],
            "advertencia": ("Un binding propuesto NO es una medición. No escribas que el "
                            "informe mide los propuestos."),
        },
        # ── Las salvedades que NO son opcionales ──────────────────────────────────────────
        # Un indicador verificado por identidad de concepto NO se contrastó contra la línea
        # base de la ley. Decir «lo medimos» sin decir eso le da al informe una firmeza que no
        # tiene, y es la clase de afirmación que un contradictor desarma con el articulado en
        # la mano.
        "salvedades_obligatorias_por_indicador": salvedades_obligatorias(expediente_id),
        # ── La atribución que la fuente EXIGE ────────────────────────────────────────────
        # No es cortesía editorial: hay fuentes admitidas cuya condición de uso es que se las
        # nombre. Va computada del expediente para que no dependa de que el redactor se
        # acuerde, que es exactamente como se pierde en la primera reescritura.
        "atribuciones_obligatorias_por_indicador": atribuciones_obligatorias(expediente_id),
        "regla_de_la_atribucion": (
            "Cada indicador que aparezca en `atribuciones_obligatorias_por_indicador` se "
            "publica NOMBRANDO a su fuente con el texto de `atribucion`, en la misma sección "
            "donde aparece su cifra. No la mandes al final del documento."),
        "regla_de_la_salvedad": (
            "Cada indicador que aparezca en `salvedades_obligatorias_por_indicador` se "
            "publica CON su salvedad, en la misma sección donde se afirma su veredicto. No "
            "la mandes a una nota al pie ni la resumas: dice contra qué NO se comprobó."),
        # Los dos denominadores, explícitos, para que ninguna cifra derivada elija en silencio.
        "denominadores_del_registro": {
            "indicadores_numerados_de_la_ley": len(numerados),
            "filas_medibles_con_subfilas": len(exp.indicadores),
            "nota": ("Un porcentaje cambia según cuál se use. Decí siempre cuál estás usando: "
                     "«3 de 8 indicadores» y «3 de 13 filas» son la misma realidad y suenan "
                     "distinto."),
        },
        # ── Veredictos YA COMPUTADOS. El modelo los copia, no los deriva. ──
        "veredictos_por_indicador_computados": resumen_semaforo(veredictos),
        "vocabulario_obligatorio": {
            "no_alcanzara": ("Usá esta palabra cuando el veredicto lo diga. NO la traduzcas a "
                             "«avance moderado» ni a ninguna forma que suene a progreso: es "
                             "exactamente el eufemismo que este producto existe para no "
                             "repetir."),
            "sin_medicion": "No es incumplimiento. Es que el informe no lo mide.",
            "estancada": GLOSA_ESTANCADA,
        },
        # ── Coherencia proceso-resultado ──
        "contradicciones_proceso_vs_resultado_computadas": [
            {"instrumento_de_proceso": h.instrumento, "indicador": h.indicador,
             "lectura_ya_redactada": h.frase()}
            for h in coh if h.veredicto == "contradiccion"],
        # ── Obligaciones ──
        "obligaciones_del_instrumento": resumen_obligaciones(expediente_id),
        "frases_publicables_de_obligaciones": [
            {"articulo": o.articulo, "frase": o.frase_publicable()} for o in obs],
        "regla_de_afirmacion": (
            "NUNCA escribas que una obligación se incumplió si su estado es "
            "'sin_registro_publico'. Usá la frase publicable tal como viene: el destinatario "
            "del informe suele ser el órgano obligado y una afirmación negativa sin verificar "
            "es refutable con un solo documento."),
        # ── Quién produce la evidencia. Va ANTES del cierre y no como apéndice ──
        # Es lo que decide cuánto pesa cada veredicto de arriba: un incumplimiento sostenido
        # en una cifra del propio obligado no se refuta por el número, se refuta por la
        # fuente. Si esto no llega al modelo, la sección sale redactada de memoria y el
        # informe cita «lo dice el Banco Mundial» sobre datos que produjo el evaluado.
        "verificabilidad_de_la_evidencia_computada": verificabilidad_publicable(expediente_id),
        "regla_del_emisor": (
            "El emisor NO es el productor. Antes de escribir que una cifra «la mide» un "
            "organismo internacional, mirá su `origen`: si dice `declarado_por_el_evaluado`, "
            "ese organismo la retransmite y quien la produjo es el Estado evaluado. "
            "Escribirlo al revés le da al informe una independencia que no tiene, y un "
            "contradictor la desarma en una línea."),
        # ── El estado del CAMPO, que es distinto de la cobertura ──────────────────────
        # La cobertura dice cuántos indicadores se miden. Ésta dice cuántos están declarados,
        # con veredicto o con motivo. Sin ella el informe se lee como si los 65 restantes no
        # existieran, cuando de 45 de ellos se puede decir exactamente por qué no se miden.
        "estado_del_campo_computado": resumen_del_campo(expediente_id),
        "regla_del_campo_cerrado": (
            "«Campo cerrado» significa que ningún indicador quedó en silencio, NO que todos "
            "tengan respuesta. Si escribís que el campo está cerrado, escribí en la misma "
            "frase cuántos tienen motivo definitivo y cuántos esperan trabajo de SDQ. La "
            "cifra sola se lee como cobertura y no lo es."),
        # ── Cierre del informe: brecha + recomendación ──
        "brechas_de_medicion": resumen_brecha(br, len(numerados)),
        "recomendaciones_ya_redactadas": [
            {"clase": r.clase, "texto": r.frase(), "desbloquea_indicadores": r.desbloquea}
            for r in recs],
        "alcance_de_la_recomendacion": (
            "Se recomienda la PUBLICACIÓN del dato, nunca la política. No propongas qué "
            "debería hacer el Estado con un indicador; solo qué falta y quién debe producirlo."),
    }


def secciones_sin_dato(ctx: Dict[str, Any]) -> List[str]:
    """Qué NO se puede escribir con este contexto. Se declara en vez de rellenarse."""
    faltan = []
    if not ctx["cobertura_indicadores_medidos_sobre_total_de_la_ley"]["medidos"]:
        faltan.append("cumplimiento")
    if not ctx["contradicciones_proceso_vs_resultado_computadas"]:
        faltan.append("coherencia_proceso")
    # Sin nada medido ni ninguna obligación con algo que verificar, la sección no tiene
    # cadena que mostrar. Se declara en vez de salir con los denominadores en cero, que se
    # leerían como «no depende del evaluado» — la lectura exactamente opuesta.
    if not ctx["verificabilidad_de_la_evidencia_computada"]["cadena_por_sujeto"]:
        faltan.append("verificabilidad")
    return faltan
