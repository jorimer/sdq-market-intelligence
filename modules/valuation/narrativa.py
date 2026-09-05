"""La prosa del eje, COMPUTADA — y los cinco puntos de la barra de insight por construcción.

La barra de insight es una rúbrica que la casa aplica a la prosa de IA: postura, mecanismo,
asimetría, falsabilidad y decisión. Este eje **no usa el motor de IA** —un informe de spreads,
rangos y sensibilidad no tiene nada que redactar, y un modelo redactándolo inventaría justo
los números que existe para probar—, así que los cinco puntos dejan de ser una esperanza y
pasan a ser **invariantes del texto**, verificables con un test.

Cómo los cumple cada párrafo del resumen:

1. **POSTURA** — abre con el veredicto sobre `ROE − Ke`, no con un dato de contexto ni con el
   valor. Un consejo que ve el spread entiende la palanca; uno que ve solo el valor discute el
   supuesto.
2. **MECANISMO** — nombra el canal: la entidad crea valor porque rinde por encima de lo que
   su capital exige, y dice de qué depende esa diferencia.
3. **ASIMETRÍA** — cuantifica los dos extremos del rango de `Ke`, que es exactamente «qué tan
   caro es equivocarse en cada dirección».
4. **FALSABILIDAD** — dice qué haría cambiar la lectura: cuánto tendría que moverse `Ke` o el
   ROE para que el signo se dé vuelta.
5. **DECISIÓN** — conecta con lo que la audiencia decide: qué supuesto habría que creer para
   sostener un precio, no una recomendación de comprar o vender.
"""
from __future__ import annotations

from typing import Optional, Tuple

from modules.valuation.service import Lectura

#: Cuánto tiene que moverse Ke para dar vuelta el signo — se computa, no se estima a ojo.
def _cuanto_falta_para_cambiar_de_signo(lec: Lectura) -> float:
    """Puntos porcentuales que `Ke` tendría que moverse para invertir la lectura."""
    if lec.cambia_de_signo:
        return 0.0
    if lec.spread_alto_pp < 0:                      # destruye en todo el rango
        return round(lec.ke_bajo_pct - lec.roe_proyectado_pct, 2)
    return round(lec.roe_proyectado_pct - lec.ke_alto_pct, 2)


def resumen_del_spread(lec: Lectura) -> str:
    """El párrafo que ABRE el informe. Los cinco puntos, en orden."""
    # 1 · POSTURA — el veredicto primero, y el número después como respaldo.
    if lec.cambia_de_signo:
        postura = (
            f"**{lec.entidad} no tiene una respuesta única sobre si crea o destruye valor**, y "
            "ése es el hallazgo. Con un ROE proyectado de "
            f"**{lec.roe_proyectado_pct:.2f} %** y un costo de capital estimado entre "
            f"**{lec.ke_bajo_pct:.2f} % y {lec.ke_alto_pct:.2f} %**, el spread va de "
            f"**{lec.spread_alto_pp:+.2f} pp a {lec.spread_bajo_pp:+.2f} pp**: cruza el cero "
            "dentro del rango.")
    elif lec.destruye_valor:
        postura = (
            f"**{lec.entidad} está destruyendo valor en todo el rango razonable de costo de "
            f"capital.** Su ROE proyectado de **{lec.roe_proyectado_pct:.2f} %** queda por "
            f"debajo de un `Ke` de entre **{lec.ke_bajo_pct:.2f} % y {lec.ke_alto_pct:.2f} %**, "
            f"con un spread de **{lec.spread_alto_pp:+.2f} a {lec.spread_bajo_pp:+.2f} pp**.")
    else:
        postura = (
            f"**{lec.entidad} crea valor en todo el rango razonable de costo de capital.** Su "
            f"ROE proyectado de **{lec.roe_proyectado_pct:.2f} %** supera un `Ke` de entre "
            f"**{lec.ke_bajo_pct:.2f} % y {lec.ke_alto_pct:.2f} %**, con un spread de "
            f"**{lec.spread_alto_pp:+.2f} a {lec.spread_bajo_pp:+.2f} pp**.")

    # 2 · MECANISMO — el canal causal, no solo el qué.
    mecanismo = (
        "El canal es directo: el valor por encima del libro es el valor presente de lo que la "
        "entidad gana **por encima de lo que su capital exige**. Si el ROE iguala al costo de "
        "capital, la entidad vale exactamente su patrimonio contable — ni más ni menos, por "
        "mucho que crezca. Crecer solo agrega valor cuando el spread es positivo; con spread "
        "negativo, **crecer destruye más rápido**.")

    # 3 · ASIMETRÍA — qué tan caro es equivocarse en cada dirección.
    asimetria = (
        f"Qué está en juego: en el extremo favorable del rango la entidad vale "
        f"**{lec.pb_alto:.2f}× su libro**; en el adverso, **{lec.pb_bajo:.2f}×**. La distancia "
        f"entre los dos —{(lec.pb_alto - lec.pb_bajo):.2f}×— no viene del negocio sino del "
        "costo de capital, que **no se observa: se estima**. Por eso no se publica un punto "
        "medio: promediar los extremos daría una cifra que ningún supuesto sostiene.")

    # 4 · FALSABILIDAD — qué haría cambiar la lectura.
    if lec.cambia_de_signo:
        falsable = (
            "Qué resolvería la ambigüedad: que el ROE se sostenga fuera del rango de `Ke` "
            "—hacia arriba o hacia abajo— por varios trimestres, o que la curva en pesos se "
            "mueva lo suficiente para angostar el rango. Mientras el ROE caiga adentro, "
            "cualquier veredicto único es una elección de supuesto, no una lectura del dato.")
    else:
        margen = _cuanto_falta_para_cambiar_de_signo(lec)
        falsable = (
            f"Qué cambiaría la lectura: un movimiento de **{abs(margen):.2f} pp** en el costo "
            "de capital o en el ROE sostenido da vuelta el signo. Eso es lo que hay que "
            "vigilar — la curva en pesos a más de dos años y la trayectoria del ROE sobre "
            "patrimonio de apertura, que es la base con la que se computa acá.")

    # 5 · DECISIÓN — el «y por tanto» de la audiencia.
    decision = (
        "Para decidir: la pregunta no es si el número es correcto sino **qué supuesto habría "
        "que creer** para sostener un precio. Un comprador que pague por encima del extremo "
        "alto está afirmando un ROE mayor o un costo de capital menor que los de acá, y esa "
        "afirmación se puede discutir con evidencia. Nada de esto es una recomendación de "
        "comprar o vender.")

    return "\n\n".join([postura, mecanismo, asimetria, falsable, decision])


def resumen_del_valor(lec: Lectura) -> str:
    cruza = ""
    if lec.valor_bajo < lec.patrimonio_libro < lec.valor_alto:
        cruza = (" El rango **cruza el patrimonio contable**: según qué extremo del costo de "
                 "capital se tome, la entidad vale más o menos que su libro.")
    return (
        f"Valor estimado entre **{lec.valor_bajo:,.0f}** y **{lec.valor_alto:,.0f}** "
        f"{lec.moneda}, contra un patrimonio libro de **{lec.patrimonio_libro:,.0f}**. El "
        f"múltiplo P/B implícito va de **{lec.pb_bajo:.2f}× a {lec.pb_alto:.2f}×**, y es "
        f"**derivado**: sale del valor, no lo produce.{cruza}\n\n"
        f"El **{lec.fraccion_de_rubrica:.0%}** del costo de capital descansa en supuestos de "
        "comparables —la beta y la prima de riesgo de mercado— y no en dato dominicano "
        "observado. Se dice porque cambia cuánto pesa la conclusión.")


def resumen_de_descomposicion(lec: Lectura) -> str:
    exceso_alto = lec.valor_alto - lec.patrimonio_libro
    exceso_bajo = lec.valor_bajo - lec.patrimonio_libro
    return (
        f"Del valor, **{lec.patrimonio_libro:,.0f} {lec.moneda} son libro**. El resto es el "
        f"valor presente del exceso: entre **{exceso_bajo:,.0f}** y **{exceso_alto:,.0f}**.\n\n"
        + ("En el extremo adverso ese exceso es **negativo**: la entidad valdría menos que su "
           "patrimonio contable.\n\n" if exceso_bajo < 0 else "")
        + "El patrimonio se toma del estado publicado por la Superintendencia, y el ROE se "
          "**recalcula sobre patrimonio de apertura** — la SIB lo publica sobre patrimonio "
          "promedio, y mezclar las dos bases mete un error sistemático que crece con el "
          "crecimiento de la entidad.")


# ── Las secciones que completan un informe de valuación profesional ──────────────────
#
# El informe tenía cinco secciones y le faltaba lo que un comité pide antes de discutir un
# número: para qué se hizo, quién puede usarlo, qué entidad es, cómo se ve su historia y con
# qué método se llegó al valor. Se agregan computadas del dato, igual que el resto.
#
# **Sin EBITDA, y a propósito.** El estándar genérico de valuación de empresas lo pide; en una
# entidad financiera no significa nada — no hay depreciación relevante, el interés no es un
# costo de financiamiento sino el negocio, y el apalancamiento es materia prima. El análisis
# va sobre lo que sí mide a un banco.

#: Nombres legibles de los tipos que supervisa la Superintendencia, con el participio ya
#: concordado. Se guarda la frase entera y no solo el sustantivo porque «asociación
#: supervisado» y «banco supervisada» salen mal, y el género no se puede deducir del slug.
#: Clave → (con artículo, sin artículo). Las dos formas ya concordadas: el género no se
#: deduce del slug, y «un asociación» o «asociación supervisado» son errores que ningún test
#: numérico ve.
_TIPOS = {
    "banca_multiple": ("un banco múltiple supervisado", "banco múltiple supervisado"),
    "banco_ahorro_credito": ("un banco de ahorro y crédito supervisado",
                             "banco de ahorro y crédito supervisado"),
    "corporacion_credito": ("una corporación de crédito supervisada",
                            "corporación de crédito supervisada"),
    "aap": ("una asociación de ahorros y préstamos supervisada",
            "asociación de ahorros y préstamos supervisada"),
}
#: Cuando el tipo no llega. No se inventa uno: se dice que no se conoce.
_TIPO_DESCONOCIDO = ("una entidad de intermediación supervisada",
                     "entidad de intermediación supervisada")


def resumen_ejecutivo(lec: Lectura) -> str:
    """Lo que un lector que no va a leer el resto tiene que llevarse.

    Abre por la CONCLUSIÓN —cuánto vale y sobre qué base— y sigue por lo que la sostiene.
    Es la única sección que puede leerse sola, así que declara sus propios límites en vez de
    remitir a la de limitaciones.
    """
    signo = ("crea valor en todo el rango" if lec.spread_bajo_pp > 0
             else "destruye valor en todo el rango" if lec.spread_alto_pp < 0
             else "**cambia de signo** dentro del rango de costo de capital")
    tipo = _TIPOS.get(lec.tipo_de_entidad, _TIPO_DESCONOCIDO)[1]
    return (
        f"**{lec.entidad}** —{tipo} por la Superintendencia de Bancos— se valúa "
        f"entre **{lec.valor_bajo:,.0f}** y **{lec.valor_alto:,.0f}** {lec.moneda} al cierre "
        f"de **{lec.periodo}**, contra un patrimonio contable de "
        f"**{lec.patrimonio_libro:,.0f}**. El múltiplo implícito va de **{lec.pb_bajo:.2f}× a "
        f"{lec.pb_alto:.2f}×** el valor libro.\n\n"
        f"**El método es Excess Return**: el valor es el patrimonio contable más el valor "
        f"presente de lo que la entidad gana por encima de lo que su capital exige. Con un "
        f"ROE proyectado de **{lec.roe_proyectado_pct:.2f} %** contra un costo de capital de "
        f"**{lec.ke_bajo_pct:.2f} % a {lec.ke_alto_pct:.2f} %**, la entidad {signo}.\n\n"
        f"**El resultado es un rango y no un punto**, y la amplitud no viene del negocio sino "
        f"del costo de capital, que no se observa. Promediar los extremos daría una cifra que "
        f"ningún supuesto sostiene. Esta valuación **no está contrastada contra precios "
        f"pagados** y no es una recomendación de comprar ni de vender.")


def proposito_y_alcance(lec: Lectura) -> str:
    """Para qué sirve este informe y para qué no. Es lo que separa una valuación de una
    opinión, y lo que un tercero necesita para saber si puede apoyarse en ella."""
    return (
        "**Qué responde.** Cuánto vale el patrimonio de la entidad bajo un modelo de Excess "
        "Return, con los estados que publica la Superintendencia de Bancos y un costo de "
        "capital construido sobre la curva soberana en pesos. Es una valuación de **negocio "
        "en marcha**: supone que la entidad sigue operando, no que se liquida.\n\n"
        "**Para qué está pensado.** Discusión de comité, encuadre de una negociación, "
        "seguimiento de la creación de valor de una participación. La pregunta que contesta "
        "no es «cuánto se pagaría» sino **qué habría que creer para sostener un precio**.\n\n"
        "**Qué NO es.** No es una tasación con fines fiscales ni un fairness opinion; no "
        "sustituye una diligencia; no incorpora información no pública ni conversaciones con "
        "la administración de la entidad. Se construye enteramente con **información "
        "pública** — que es también lo que lo hace reproducible por un tercero.\n\n"
        "**Quién puede usarlo.** El destinatario del informe. Un tercero que lo reciba tiene "
        "que leer las secciones de metodología y limitaciones antes de apoyarse en la cifra: "
        "el rango depende de supuestos declarados que ese tercero puede no compartir.")


def antecedentes(lec: Lectura, *, posicion: Optional[Tuple[int, int]] = None,
                 cuota_pct: Optional[float] = None) -> str:
    """Qué entidad es y dónde está parada. `posicion` es `(puesto, de_cuántas)` DENTRO de su
    tipo, y la cuota su participación en el patrimonio de ese grupo — las dos computadas,
    porque una posición de mercado afirmada sin computarla es una opinión."""
    tipo = _TIPOS.get(lec.tipo_de_entidad, _TIPO_DESCONOCIDO)[0]
    partes = [
        f"**{lec.entidad}** es **{tipo}** por la Superintendencia de Bancos "
        f"de la República Dominicana. Al cierre de {lec.periodo} su patrimonio contable era "
        f"de **{lec.patrimonio_libro:,.0f} {lec.moneda}**."
    ]
    if posicion is not None:
        puesto, total = posicion
        cuota = f", con el **{cuota_pct:.1f} %** del patrimonio del grupo" if cuota_pct else ""
        partes.append(
            f"Dentro de su tipo ocupa el **puesto {puesto} de {total}** por patrimonio{cuota}. "
            "La posición se computa sobre el padrón completo de su clase al mismo corte, no "
            "sobre una selección: comparar contra un subconjunto elegido haría ver a "
            "cualquier entidad como se la quiera hacer ver.")
    partes.append(
        "**Por qué el tipo importa para valuar.** Los parámetros del modelo —beta, retención "
        "de utilidades y persistencia del exceso— se estiman POR TIPO de entidad, porque las "
        "cuatro clases se comportan distinto y tratarlas igual metía un error sistemático. "
        "Los de esta entidad, con lo que los sostiene, van en la sección de metodología.")
    partes.append(
        "**Lo que este informe NO conoce de la entidad**: su composición accionaria, su "
        "historia de control, su plan de negocio y cualquier hecho posterior al cierre "
        "valuado. Se construye con los estados publicados y nada más, y eso acota lo que "
        "puede afirmar.")
    return "\n\n".join(partes)


def analisis_financiero(lec: Lectura) -> str:
    """La historia con la que se proyecta, y su lectura.

    Sin EBITDA: en una entidad financiera no significa nada. Lo que mide a un banco es el
    retorno sobre el capital que estuvo disponible para ganar, y cómo creció ese capital.
    """
    serie = lec.serie_spread
    if not serie:
        return ("No hay serie de ROE publicada suficiente para el análisis histórico: hacen "
                "falta al menos dos cierres con patrimonio para computar un retorno sobre "
                "patrimonio de apertura. Se declara en vez de proyectar sobre un solo punto.")
    filas = "\n".join(f"| {p} | {r:.2f} % |" for p, r in serie)
    roes = [r for _p, r in serie]
    minimo, maximo = min(roes), max(roes)
    amplitud = maximo - minimo
    lectura = (
        "El ROE se mueve poco en la serie observada, así que proyectar el nivel reciente es "
        "razonable." if amplitud < 4 else
        f"El ROE se mueve **{amplitud:.1f} pp** entre su mínimo y su máximo en la serie "
        "observada. Un promedio de esa serie escondería la dispersión, así que el modelo "
        "proyecta el nivel reciente y la sección de sensibilidad muestra qué pasa si no se "
        "sostiene.")
    return (
        "**Retorno sobre patrimonio de APERTURA**, que es el capital que efectivamente estuvo "
        "disponible para ganar durante el período:\n\n"
        f"| Cierre | ROE |\n|---|---|\n{filas}\n\n"
        f"{lectura}\n\n"
        f"El **ROE proyectado** para la valuación es **{lec.roe_proyectado_pct:.2f} %**.\n\n"
        "**Dos precisiones sobre esta tabla.** La primera: la Superintendencia publica el ROE "
        "sobre patrimonio PROMEDIO y acá se recalcula sobre APERTURA, así que las cifras no "
        "coinciden con las suyas — y la diferencia crece con el crecimiento de la entidad. La "
        "segunda: **no se usa EBITDA**. En una entidad financiera no mide nada: no hay "
        "depreciación relevante, el interés no es un costo de financiamiento sino el negocio, "
        "y el apalancamiento es materia prima y no estructura de capital.")


def metodologia(lec: Lectura) -> str:
    """Cómo se construyó el número. Es la sección que permite discutirlo."""
    return (
        "**Enfoque: ingreso, por Excess Return.** El valor del patrimonio es el patrimonio "
        "contable más el valor presente del *residual income* — lo que la entidad gana por "
        "encima de lo que su capital exige:\n\n"
        "> `valor = BV(0) + suma de RI_t/(1+Ke)^t + terminal`, con `RI_t = (ROE_t − Ke) x BV(t−1)`\n\n"
        "La perpetuidad es de **residual income y no de utilidad**: con el terminal sobre "
        "utilidad, una entidad cuyo ROE iguala su costo de capital —que por definición vale "
        "exactamente su libro— saldría valiendo mucho más.\n\n"
        f"**El terminal EROSIONA el exceso**, no lo perpetúa: `ω·RI_T/(1+Ke−ω)` con una "
        f"persistencia medida de **{lec.persistencia:.3f}** para su tipo de entidad. Suponer "
        "que una ventaja dura para siempre —y encima crece— hace explotar el resultado por "
        "los dos lados: es lo que da múltiplos de doce veces el libro para una entidad muy "
        "rentable, y de dos décimas para una que gana por debajo de su costo de capital. La "
        "erosión es lo que dice el equilibrio competitivo y lo que muestran los datos "
        "dominicanos.\n\n"
        f"**Costo de capital en pesos, tres términos: `Ke = Rf + β × ERP`.** Sin prima de "
        "riesgo país: una tasa libre de riesgo EN PESOS ya lleva adentro el riesgo soberano "
        "y la inflación esperada, y sumarle el país encima lo cuenta dos veces. La `Rf` sale "
        "de la curva de valores subastados del Banco Central a más de dos años. **La beta no "
        "se desapalanca**: Hamada supone que la deuda es financiamiento con un apalancamiento "
        "óptimo separable de la operación, y en un banco los depósitos son materia prima.\n\n"
        f"**Los parámetros dependen del TIPO de entidad.** Para ésta: persistencia "
        f"{lec.persistencia:.3f} y retención de utilidades {lec.retencion:.2f}. "
        f"{lec.evidencia_del_tipo}\n\n"
        "**Enfoque de mercado, como contraste y no como método.** El panel de transacciones "
        "bancarias del Caribe dice a cuánto sobre libro se ha pagado por una entidad, y sirve "
        "para ver si el rango de salida es razonable. No se usa para producir el valor: son "
        "pocas operaciones, de jurisdicciones y años distintos, y calibrar contra ellas sería "
        "ajustar el modelo a un puñado de observaciones.")


def fuentes_y_procedencia(lec: Lectura) -> str:
    """De dónde salió cada insumo. Un informe que no se puede rastrear no se puede auditar."""
    avisos = ""
    if lec.advertencias:
        cuerpo = "\n".join(f"* {a}" for a in lec.advertencias)
        avisos = f"\n\n**Avisos que la corrida dejó registrados:**\n\n{cuerpo}"
    return (
        "| Insumo | Fuente | Naturaleza |\n|---|---|---|\n"
        "| Patrimonio y resultado por entidad | Superintendencia de Bancos · estados de "
        "situación y de resultados | dato publicado |\n"
        "| Verificación del patrimonio | SIMBAD · Superset público de la SB | dato publicado |\n"
        "| Tasa libre de riesgo en pesos | BCRD · cuadro V.1, valores subastados en moneda "
        "nacional, plazo de más de dos años | dato publicado |\n"
        "| Techo de crecimiento terminal | BCRD · variación interanual del PIB nominal, "
        "mediana de la serie | dato publicado |\n"
        "| Retención de utilidades y persistencia del exceso | medidas sobre el padrón "
        "completo de la SB, cierres 2019-2025 | estimación propia |\n"
        "| Beta y prima de riesgo de mercado | comparables latinoamericanos | **rúbrica** |\n\n"
        f"El **{lec.fraccion_de_rubrica:.0%}** del costo de capital descansa en la última "
        "fila. Es la parte del resultado que no se apoya en dato dominicano observado, y por "
        "eso se publica el rango completo en vez de un punto.\n\n"
        "**Nada de este informe usa información no pública.** Todo insumo es reproducible por "
        "un tercero con las mismas fuentes, que es la condición para que la cifra se pueda "
        "discutir en vez de aceptarse."
        + avisos)


def limitaciones(lec: Lectura) -> str:
    """Las condiciones bajo las que vale la cifra, y las que la invalidan.

    Se computa de la lectura y no se transcribe de la muestra: era una de las dos secciones
    que un informe REAL servía con el texto ilustrativo.
    """
    partes = [
        "**Esta valuación no está contrastada contra precios pagados.** El panel de "
        "transacciones bancarias del Caribe permite decir a cuánto sobre valor libro se ha "
        "pagado por una entidad —una referencia de mercado— pero contrastar ESTE modelo es "
        "otra cosa: exige valuar cada adquirida a la fecha de su operación, y para eso hace "
        "falta su historia de balance. Mientras eso no exista, el eje no afirma que sus "
        "valores predicen precios.",
        f"**El costo de capital no se observa.** El **{lec.fraccion_de_rubrica:.0%}** de `Ke` "
        "descansa en la beta y la prima de riesgo de mercado, que son supuestos de "
        "comparables latinoamericanos: la República Dominicana no tiene entidades "
        "financieras cotizadas contra las cuales medirlos. Por eso el resultado es un rango.",
    ]
    if lec.cambia_de_signo:
        partes.append(
            "**El valor CAMBIA DE SIGNO dentro del rango de costo de capital.** No es un "
            "defecto del cálculo: es el hallazgo. Que la entidad cree o destruya valor "
            "depende de un supuesto que no se observa, y quien decida sobre esta cifra tiene "
            "que tomar posición sobre ese supuesto antes que sobre el número.")
    partes += [
        "**Valuación de negocio en marcha, a una fecha.** Supone que la entidad sigue "
        f"operando y usa los estados al cierre de **{lec.periodo}**. No incorpora hechos "
        "posteriores, información no pública, ni conversaciones con la administración.",
        "**Un score de solidez no es un proxy de precio.** Una entidad sólida puede estar "
        "destruyendo valor, y este informe responde cuánto vale, no qué tan sana está.",
        "**Nada de lo anterior es una recomendación de comprar o vender.** Las opiniones son "
        "de SDQ Consulting y no constituyen asesoría de inversión.",
    ]
    return "\n\n".join(partes)
