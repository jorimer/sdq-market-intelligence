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
