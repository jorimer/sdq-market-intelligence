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
from modules.law_intel.campo import campo as campo_del_expediente
from modules.law_intel.campo import resumen as resumen_del_campo
from modules.law_intel.obligaciones import cargar_obligaciones
from modules.law_intel.obligaciones import resumen as resumen_obligaciones
from modules.law_intel.ratificacion import publicable as ratificacion_publicable
from modules.law_intel.registro import cargar
from modules.law_intel.scoring.accionabilidad import recomendaciones
from modules.law_intel.scoring.brecha import brechas
from modules.law_intel.scoring.brecha import resumen as resumen_brecha
from modules.law_intel.scoring.coherencia_proceso import revisar
from modules.law_intel.scoring.fines import por_fin
from modules.law_intel.scoring.fines import publicable as fines_publicable
from modules.law_intel.scoring.pendiente import horizonte_de
from modules.law_intel.scoring.pendiente import panel as panel_pendiente
from modules.law_intel.scoring.pendiente import publicable as pendiente_publicable
from modules.law_intel.scoring.semaforo import panel
from modules.law_intel.scoring.semaforo import resumen as resumen_semaforo
from modules.law_intel.scoring.semaforo import tabla as tabla_semaforo
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
    nombres = {i.id: i.nombre for i in cargar(expediente_id).numerados}
    return [{"indicador": b.indicador,
             # El nombre viaja con el número también acá: una fila que dice «2.35» y nada más
             # obliga al redactor a buscarle un rótulo, y el que encuentra es el de al lado.
             "nombre_del_indicador": nombres.get(b.indicador, ""),
             "camino": b.verificado_por,
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
    nombres = {i.id: i.nombre for i in exp.numerados}
    return [{"indicador": b.indicador,
             "nombre_del_indicador": nombres.get(b.indicador, ""),
             "fuente": b.fuente,
             "atribucion": str(exigen[b.fuente].get("atribucion") or "").strip()}
            for b in sorted(cargar_bindings(expediente_id).values(), key=lambda x: x.indicador)
            if b.cuenta and b.fuente in exigen]


def _n(v: Any) -> int:
    """Un conteo de los resúmenes, como entero. Existe para que el tipo no se pierda: los
    resúmenes se tipan como `Dict[str, object]` y de ahí no sale aritmética comprobable."""
    return int(v) if isinstance(v, (int, float)) else 0


def _bloque(d: Dict[str, Any], clave: str) -> Dict[str, Any]:
    """Un sub-diccionario de un resumen, tipado. Los resúmenes se declaran como
    `Dict[str, object]` y de ahí no sale un `.get` comprobable."""
    v = d.get(clave)
    return v if isinstance(v, dict) else {}


def _con_nombres(nodo: Any, nombres: Dict[str, str]) -> Any:
    """Le pega el nombre del indicador a toda fila que lo cite por su número.

    Recorre en vez de tocar cada bloque a mano: el hueco entra siempre por el bloque que
    alguien agregó después, y acá el hueco se paga publicando un indicador de agua potable
    como si midiera acceso a antirretrovirales.
    """
    if isinstance(nodo, dict):
        fila = {k: _con_nombres(v, nombres) for k, v in nodo.items()}
        ident = fila.get("indicador")
        if isinstance(ident, str) and ident in nombres and not any(
                "nombre" in k for k in fila):
            fila["nombre_del_indicador"] = nombres[ident]
        return fila
    if isinstance(nodo, list):
        return [_con_nombres(x, nombres) for x in nodo]
    return nodo


def law_ai_context(expediente_id: str, corte: str,
                   series: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    numerados = exp.numerados
    veredictos = panel(numerados, bs, series or {}, corte)
    motivos_del_campo = {k: c.estado for k, c in campo_del_expediente(
        expediente_id).items()}
    br = brechas(numerados, bs, motivos_del_campo)
    obs = cargar_obligaciones(expediente_id)
    recs = recomendaciones(br, obs)
    coh = revisar(expediente_id, {i.id: i for i in exp.indicadores}, corte)
    cob = cobertura(expediente_id)
    res_semaforo = resumen_semaforo(veredictos)
    nombres_de_indicador = {i.id: i.nombre for i in numerados}
    # El FIN es la unidad de lectura del informe. Se computa acá —y no en el prompt— porque
    # «la mayoría» de siete contra veintiuno es una relación, y las relaciones se computan.
    fines = por_fin(numerados, veredictos, exp.meta.get("ejes") or {})
    # Lo PENDIENTE: las metas que aún no vencen, proyectadas al horizonte que declara la
    # propia ley. Solo si ese horizonte es posterior al corte — una ley ya vencida no tiene
    # nada por delante, y proyectar hacia atrás sería inventar un plazo.
    horizonte = horizonte_de(exp.meta)
    pendientes = (panel_pendiente(numerados, bs, series or {}, horizonte)
                  if horizonte and horizonte > corte else [])

    ctx: Dict[str, Any] = {
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
        # ── Las POBLACIONES de la ley, contadas una sola vez. ──
        # Existe porque el informe generado se contradijo consigo mismo: dijo «veredicto
        # sobre 44 de esos 90» en una sección y «sobre 46 de esos 90» en otra, y las dos
        # citaban la plataforma. Son dos poblaciones distintas que además dan 44 y 46
        # cruzados —los medidos son 46 y los sin medición son 44—, así que el mismo número
        # significa dos cosas según de dónde se lea.
        #
        # Acá viven todas, con su nombre completo y su porcentaje ya computado. Ninguna
        # sección deriva una división.
        "poblaciones_de_la_ley": {
            "indicadores_que_la_ley_numera": len(numerados),
            "medidos_con_serie_verificada": cob["medidos"],
            "con_veredicto_de_cumplimiento": _n(res_semaforo["evaluados"]),
            "medidos_sin_observacion_utilizable": (
                _n(cob["medidos"]) - _n(res_semaforo["evaluados"])),
            "sin_medicion_con_motivo_declarado": len(numerados) - _n(cob["medidos"]),
            "alcanzan_su_meta": _n(res_semaforo["cumplen"]),
            "nota": (
                "«Medido» y «con veredicto de cumplimiento» NO son lo mismo: un indicador "
                "puede tener serie verificada y no tener observación utilizable al corte. Y "
                "dos poblaciones distintas de esta misma tabla pueden coincidir en el mismo "
                "número por azar; que dos cifras sean iguales no las vuelve la misma cosa. "
                "Nombrá siempre cuál estás usando y copiá el valor de acá."),
        },
        # ── Tres poblaciones que se dicen con las mismas palabras. ──
        # El informe generado escribió «8», «14» y «24» para lo que redactó como «los
        # instrumentos que la propia ley eligió y ya no están disponibles». Las tres cifras
        # son reales y ninguna significa eso salvo la del medio. Cada una llega acá con su
        # frase ya escrita, para que el modelo copie en vez de parafrasear.
        "no_confundir_estas_poblaciones": {
            "instrumento_de_medicion_discontinuado": {
                "n": _n(_bloque(resumen_del_campo(expediente_id),
                                "por_estado").get("instrumento_discontinuado", 0)),
                "lectura_ya_redactada": (
                    "indicadores sin veredicto porque el instrumento que los medía dejó de "
                    "aplicarse"),
            },
            "instrumentos_de_tercero_que_la_ley_eligio_y_se_perdieron": {
                "n": _n(_bloque(verificabilidad_publicable(expediente_id),
                                "instrumentos_de_tercero_que_la_ley_eligio").get(
                    "perdidos", 0)),
                "lectura_ya_redactada": (
                    "indicadores que la ley previó verificar con un instrumento aplicado por "
                    "un tercero y que perdieron esa fuente. NO es lo mismo que quedarse sin "
                    "medición: varios se miden hoy por otra vía, con la independencia "
                    "perdida"),
            },
            "brechas_cuya_causa_esta_en_el_texto_de_la_ley": {
                "n": _n(_bloque(resumen_brecha(br, len(numerados)),
                                "por_responsable").get("instrumento", 0)),
                "lectura_ya_redactada": (
                    "indicadores que ninguna fuente vuelve medibles por cómo la ley los "
                    "escribió: metas en prosa, líneas base que no reproducen, términos que "
                    "nadie publica. NO son instrumentos discontinuados"),
            },
            "regla": (
                "Las tres cifras son distintas y describen poblaciones distintas. Copiá la "
                "`lectura_ya_redactada` de la que estés usando y no la parafrasees: la frase "
                "«el instrumento que la ley eligió ya no está disponible» solo describe a la "
                "segunda."),
        },
        # ── Cómo se llama cada indicador que la ley numera. ──
        # El diccionario canónico. Cualquier sección que cite un «2.35» resuelve acá su
        # nombre en vez de pegarle el más cercano que haya visto: así se publicó «el acceso
        # a medicamentos antirretrovirales (2.35)» sobre un indicador que mide acceso a agua
        # de la red pública. Las cifras eran correctas y el sujeto no, que es la forma más
        # cara de equivocarse en este producto.
        "nombres_de_los_indicadores_de_la_ley": nombres_de_indicador,
        "regla_del_nombre_del_indicador": (
            "Cuando cites un indicador por su número, su nombre sale de "
            "`nombres_de_los_indicadores_de_la_ley` y de ningún otro lado. No lo deduzcas "
            "del contexto ni lo recuerdes de otra sección: dos indicadores consecutivos "
            "miden cosas distintas y el lector verifica el rótulo contra la ley."),
        # ── El FIN de la ley: la pregunta que el lector trae. ──
        # Va ANTES del inventario de indicadores a propósito: quien lee quiere saber si la
        # ley está consiguiendo lo que se propuso, y el conteo por indicador es la evidencia
        # de esa respuesta, no la respuesta.
        **fines_publicable(fines),
        # ── Lo que la ley todavía tiene por delante. ──
        # Una meta que no venció NO se puede incumplir: este bloque trae su propio
        # vocabulario justamente para que el modelo no arrastre el del corte vencido.
        **(pendiente_publicable(pendientes, horizonte)
           if pendientes and horizonte else {}),
        # ── Veredictos YA COMPUTADOS. El modelo los copia, no los deriva. ──
        "veredictos_por_indicador_computados": res_semaforo,
        # La EVIDENCIA, fila por fila. El resumen de arriba dice cuántos; esta dice cuáles,
        # con su meta y su valor. Sin ella, a las secciones que deben nombrar indicadores se
        # les pedía la lista y se les daba el conteo — y las metas salían reconstruidas de
        # memoria: «2.7 contra una meta de 0.42» cuando la ley fija 0.44.
        "tabla_de_veredictos_por_indicador": tabla_semaforo(
            veredictos, numerados, exp.meta.get("ejes") or {}),
        "regla_de_la_tabla": (
            "Toda cifra que atribuyas a un indicador —su meta, su valor observado, su "
            "distancia— sale de `tabla_de_veredictos_por_indicador` y de ningún otro lado. No "
            "la recuerdes de otra sección ni la deduzcas del nombre del indicador. Y el "
            "reparto por fin se cuenta sobre esta tabla, no a ojo."),
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
        # `por_tipo` se RETIRA del contexto: clasifica por la estructura del binding y no
        # coincide con la composición del campo, que es la que se cita. Servirla con una
        # advertencia de que no se use era dejar la contradicción a mano del redactor.
        "brechas_de_medicion": {k: v for k, v in resumen_brecha(br, len(numerados)).items()
                                if k not in ("por_tipo", "advertencia_sobre_por_tipo")},
        "recomendaciones_ya_redactadas": [
            {"clase": r.clase, "texto": r.frase(), "desbloquea_indicadores": r.desbloquea}
            for r in recs],
        "alcance_de_la_recomendacion": (
            "Se recomienda la PUBLICACIÓN del dato, nunca la política. No propongas qué "
            "debería hacer el Estado con un indicador; solo qué falta y quién debe producirlo."),
    }
    # El sujeto viaja con el número, en TODO el contexto y no bloque por bloque: el hueco
    # entra siempre por el que alguien agregó después. Lo vigila
    # `test_una_sola_verdad_por_poblacion.py`.
    return _con_nombres(ctx, nombres_de_indicador)


def secciones_sin_dato(ctx: Dict[str, Any]) -> List[str]:
    """Qué NO se puede escribir con este contexto. Se declara en vez de rellenarse."""
    faltan = []
    if not ctx["cobertura_indicadores_medidos_sobre_total_de_la_ley"]["medidos"]:
        # Las tres secciones del espinazo dependen de que haya algo medido. Con cero
        # bindings verificados no hay nada que decir de lo logrado ni de lo no logrado, y
        # escribirlas igual produciría el Deep Dive hueco que este repositorio ya publicó.
        faltan.extend(["estado_de_la_ley", "logrado", "no_logrado"])
    # Ojo con lo que NO va acá: «ninguna meta se alcanzó» es una respuesta, no una brecha.
    # `logrado` se declara sin dato cuando no hay mediciones, nunca cuando hay mediciones y
    # el resultado es cero — eso último es justamente el hallazgo.
    pend = ctx.get("metas_pendientes_al_horizonte_de_la_ley") or {}
    if not (pend.get("por_indicador") or []):
        faltan.append("pendiente")
    if not ctx["contradicciones_proceso_vs_resultado_computadas"]:
        faltan.append("coherencia_proceso")
    # Sin nada medido ni ninguna obligación con algo que verificar, la sección no tiene
    # cadena que mostrar. Se declara en vez de salir con los denominadores en cero, que se
    # leerían como «no depende del evaluado» — la lectura exactamente opuesta.
    if not ctx["verificabilidad_de_la_evidencia_computada"]["cadena_por_sujeto"]:
        faltan.append("verificabilidad")
    return faltan
