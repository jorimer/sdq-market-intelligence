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

from typing import Any, Dict, List

from modules.law_intel.bindings import cargar_bindings, cobertura
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


def law_ai_context(expediente_id: str, corte: str) -> Dict[str, Any]:
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    numerados = exp.numerados
    veredictos = panel(numerados, bs, {}, corte)
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
            "advertencia": ("Un binding propuesto NO es una medición. No escribas que el "
                            "informe mide los propuestos."),
        },
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
    return faltan
