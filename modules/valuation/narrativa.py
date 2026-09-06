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

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

from modules.valuation.panel import transacciones as tx
from modules.valuation.service import Lectura

if TYPE_CHECKING:
    from modules.valuation.entorno import Entorno
    from modules.valuation.responsabilidad import Cierre

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


_NOMBRE_DEL_TIPO = {
    "banca_multiple": "los bancos múltiples", "banco_ahorro_credito": "los bancos de ahorro y crédito",
    "corporacion_credito": "las corporaciones de crédito",
    "aap": "las asociaciones de ahorros y préstamos"}


def entorno_macro_e_industria(ent: Optional["Entorno"], lec: Lectura) -> str:
    """La macro al corte y la industria del tipo. Cada cifra con su período; lo ausente se
    omite; las relaciones se computan en `entorno.relacion`."""
    from modules.valuation import entorno as env
    if ent is None:
        return ("El entorno macroeconómico y de industria no se pudo leer para este corte y se "
                "omite en vez de rellenarse: el informe valúa con los estados de la entidad y "
                "la curva en pesos, que sí están.")
    partes: List[str] = []
    macro: List[str] = []
    if ent.pib_interanual:
        c = ent.pib_interanual
        macro.append(f"el PIB real creció **{c.valor:.2f} %** interanual al {c.periodo}")
    if ent.inflacion_12m:
        c = ent.inflacion_12m
        macro.append(f"la inflación de doce meses fue **{c.valor:.2f} %** a {c.periodo}")
    if ent.tipo_de_cambio:
        c = ent.tipo_de_cambio
        var = (f", **{c.interanual_pct:+.2f} %** interanual" if c.interanual_pct is not None
               else "")
        macro.append(f"el tipo de cambio de referencia promedió **RD$ {c.valor:.2f}** por dólar "
                     f"en {c.periodo}{var}")
    macro.append(f"la tasa libre de riesgo en pesos con la que se valuó —curva soberana a más "
                 f"de dos años— estuvo entre **{lec.rf_pct[0]:.2f} %** y **{lec.rf_pct[1]:.2f} %**")
    partes.append(
        "**Macro al corte.** Cada cifra lleva el período de su fuente, que no siempre coincide "
        "con el corte de la entidad: " + "; ".join(macro) + ". La macro entra a la valuación "
        "por UNA sola puerta, la curva en pesos que arma el costo de capital; el resto es "
        "contexto para leer el ROE, no un insumo del número.")
    ind = ent.industria
    if ind is None:
        partes.append(
            "**Industria.** No hay padrón suficiente del tipo de la entidad al corte para "
            "comparar; se omite en vez de comparar contra un grupo de uno.")
        return "\n\n".join(partes)
    nombre = _NOMBRE_DEL_TIPO.get(ind.tipo, "las entidades de su tipo")
    filas: List[str] = []
    lecturas: List[str] = []

    def fila(rotulo: str, propio: Optional[float], tipo: Optional[float], n: int,
             unidad: str = "%") -> None:
        rel = env.relacion(propio, tipo)
        if propio is None or tipo is None:
            return
        brecha, palabra = rel if rel else (0.0, "en línea")
        nexo = "con el" if palabra == "en línea" else "del"
        filas.append(f"| {rotulo} | {propio:.2f} {unidad} | {tipo:.2f} {unidad} ({n}) | "
                     f"{brecha:+.2f} pp · {palabra} |")
        lecturas.append(f"{rotulo}: **{palabra} {nexo} resto** ({brecha:+.2f} pp)")

    fila("ROE de doce meses sobre apertura", ind.roe_entidad_pct,
         ind.roe_del_resto_del_tipo_pct, ind.n_en_roe)
    fila("Crecimiento interanual de la cartera bruta", ind.crecimiento_cartera_entidad_pct,
         ind.crecimiento_cartera_del_resto_del_tipo_pct, ind.n_en_cartera)
    fila("Morosidad (cartera vencida a 90 días / cartera bruta)", ind.morosidad_entidad_pct,
         ind.morosidad_del_resto_del_tipo_pct, ind.n_en_morosidad)
    if not filas:
        partes.append(f"**Industria.** El padrón de {nombre} al {ind.periodo} tiene "
                      f"{ind.n_entidades_del_tipo} entidades, pero ninguna de las razones se "
                      "pudo medir para las dos puntas; se omite en vez de rellenarse.")
        return "\n\n".join(partes)
    tabla = ("| Indicador | Entidad | Resto de su tipo (n) | Brecha |\n|---|---|---|---|\n"
             + "\n".join(filas))
    partes.append(
        f"**Industria: {nombre}, al {ind.periodo}.** El tipo son "
        f"**{ind.n_entidades_del_tipo} entidades** con patrimonio publicado al corte, y el "
        "comparador es el RESTO —la entidad queda fuera de su propio agregado, porque contra "
        "un total que ella domina siempre saldría en línea—; cada agregado es suma sobre suma "
        "de las que tienen las dos puntas, y el número entre paréntesis dice cuántas. El ROE "
        "del resto se computa con la MISMA base que el de la entidad —doce meses sobre "
        "patrimonio de apertura—, así que la brecha es una brecha y no una diferencia de "
        "definición.\n\n" + tabla + "\n\n"
        "Lectura computada: " + "; ".join(lecturas) + ". La brecha de ROE es lo que "
        "cuenta para el valor: el exceso sobre el costo de capital se compara contra un "
        "`Ke` común a todo el tipo, así que estar por encima del tipo en ROE es estar más "
        "lejos de destruir valor, no una garantía de crearlo.")
    return "\n\n".join(partes)


def analisis_financiero(lec: Lectura) -> str:
    """La historia con la que se proyecta, y su lectura.

    Sin EBITDA: en una entidad financiera no significa nada. Lo que mide a un banco es el
    retorno sobre el capital que estuvo disponible para ganar, y cómo creció ese capital.
    """
    serie = lec.serie_spread
    if not serie:
        return ("No hay serie de ROE publicada suficiente para el análisis histórico: hacen "
                "falta doce meses de historia —un corte y el mismo corte del año anterior, "
                "con patrimonio y utilidad publicados— para computar un retorno de doce meses "
                "sobre patrimonio de apertura. Se declara en vez de proyectar sobre un punto.")
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
        "**Retorno de DOCE MESES sobre patrimonio de APERTURA**: la utilidad de los últimos "
        "doce meses cerrados en cada corte —la Superintendencia publica el acumulado del "
        "ejercicio, y un trimestre no es un año— sobre el capital que estuvo disponible para "
        "ganarla, el de doce meses antes:\n\n"
        f"| Corte | ROE (12 meses) |\n|---|---|\n{filas}\n\n"
        f"{lectura}\n\n"
        f"El **ROE proyectado** para la valuación es **{lec.roe_proyectado_pct:.2f} %**.\n\n"
        "**Dos precisiones sobre esta tabla.** La primera: la Superintendencia publica el ROE "
        "sobre patrimonio PROMEDIO y acá se recalcula sobre APERTURA, así que las cifras no "
        "coinciden con las suyas — y la diferencia crece con el crecimiento de la entidad. La "
        "segunda: **no se usa EBITDA**. En una entidad financiera no mide nada: no hay "
        "depreciación relevante, el interés no es un costo de financiamiento sino el negocio, "
        "y el apalancamiento es materia prima y no estructura de capital.")


#: La BASE del valor. Va en la metodología —es una afirmación de método, no una brecha— y
#: va una sola vez. Cero líneas decían esto en un Deep Dive real, y un lector profesional
#: busca exactamente esta declaración antes de usar la cifra.
BASE_DEL_VALOR = (
    "**Base del valor: el 100 % del patrimonio, como participación de control, en marcha.** "
    "El Excess Return capitaliza lo que el negocio ENTERO gana por encima de su capital, así "
    "que el resultado es el valor de la entidad completa —lo que compraría quien la "
    "controla— y no el de una acción suelta. Por eso no se aplica prima de control ni "
    "descuento por iliquidez: el control ya está adentro del método, y un descuento por "
    "falta de mercado (DLOM) es un ajuste sobre una participación concreta, con sus derechos "
    "y su liquidez, que este informe no valúa. La referencia de mercado del contraste está "
    "en la misma base: el panel son compras de control.")

#: Lo que la base implica para quien lea la cifra pensando en una participación menor.
FRASE_PARTICIPACION_MINORITARIA = (
    "**La cifra es del 100 % y de una participación de control.** Una participación "
    "minoritaria, o una que no se puede transferir, no vale la fracción proporcional de este "
    "rango: el descuento que le corresponde depende de derechos y liquidez que acá no se "
    "estiman.")

#: Solo para las asociaciones de ahorros y préstamos, que son mutuales.
FRASE_AAP_SIN_ACCIONES = (
    "**Una asociación de ahorros y préstamos no tiene acciones.** Es una mutual: no hay "
    "socios que puedan vender ni participación que se compre, así que el valor es el del "
    "NEGOCIO y no el de un título. Sirve para medir si crea o destruye valor y para "
    "encuadrar una conversión o una fusión, no para fijar el precio de una compra.")


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
        f"{BASE_DEL_VALOR}\n\n"
        "**Enfoque de mercado, como contraste y no como método.** El panel de transacciones "
        "bancarias del Caribe dice a cuánto sobre libro se ha pagado por una entidad, y la "
        "sección «Contraste de mercado» sitúa el rango de salida contra su mediana y su rango. "
        "No se usa para producir el valor: son pocas operaciones, de jurisdicciones y años "
        "distintos, y calibrar contra ellas sería ajustar el modelo a un puñado de "
        "observaciones.")


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
        "| Beta y prima de riesgo de mercado | comparables latinoamericanos | **rúbrica** |\n"
        "| Panel de transacciones bancarias RD/Caribe | relevamiento propio: anuncios, memorias "
        "auditadas del comprador o de la adquirida, filings ante la SEC, SB/SIMBAD y BCRD | dato "
        "publicado + relevamiento propio |\n\n"
        # La fila se NOMBRA, no se señala por posición: decía «la última fila» y al entrar el
        # panel de transacciones al final de la tabla la frase pasó a señalar otra cosa. Lo
        # encontró leer el PDF, no un test.
        f"El **{lec.fraccion_de_rubrica:.0%}** del costo de capital descansa en la fila de "
        "beta y prima de riesgo de mercado. Es la parte del resultado que no se apoya en dato "
        "dominicano observado, y por "
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
        "transacciones bancarias del Caribe —la sección de contraste de mercado— permite decir "
        "a cuánto sobre valor libro se ha pagado por una entidad, una referencia de mercado, "
        "pero contrastar ESTE modelo es "
        "otra cosa: exige valuar cada adquirida a la fecha de su operación, y para eso hace "
        "falta su historia de balance. Mientras eso no exista, el eje no afirma que sus "
        "valores predicen precios.",
        f"**El costo de capital no se observa.** El **{lec.fraccion_de_rubrica * 100:.0f} %** de `Ke` "
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
    partes.append(FRASE_PARTICIPACION_MINORITARIA)
    if lec.tipo_de_entidad == "aap":
        partes.append(FRASE_AAP_SIN_ACCIONES)
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


# ── El contraste de mercado: el panel de transacciones LLEGA al informe ─────────────
#
# El panel se computaba entero —comparables, mediana, mínimo y máximo, el gate, las vías
# abiertas y los descartes— y el informe no lo pedía: la metodología decía que «el panel dice
# a cuánto sobre libro se ha pagado» y no mostraba ni tabla, ni rango, ni conteo. Es la
# familia «servir el dato no alcanza: hay que pedirlo». Cada eje son DOS trabajos, el motor
# y la plantilla; éste es el segundo.
#
# Tres reglas que gobiernan lo de abajo:
#
# 1. **Solo se ordena lo comparable.** A la tabla y al resumen entran los múltiplos sobre
#    base CONTABLE; los verificables sobre valor razonable de la NIIF 3 van aparte y
#    marcados, nunca ocultos — ocultarlos los hace desaparecer sin aviso.
# 2. **La posición del rango se COMPUTA.** Por debajo, por encima o solapando, y dónde cae
#    la mediana, se calculan en código y la prosa los copia. Un modelo acierta las cifras y
#    falla las relaciones; acá no hay modelo, pero la regla se conserva para que un test la
#    pueda exigir.
# 3. **Es contraste, no método.** El panel sitúa el rango de salida; no lo produce. Y un
#    panel abierto es evidencia de MERCADO, no de que este modelo acierte.

#: Subtítulos de la sección. Son constantes porque los tests parten la sección por ellos.
SUBTITULO_COMPARABLES = "Comparables sobre base contable"
SUBTITULO_OTRA_BASE = "Verificables sobre otra base, que no entran al resumen"
SUBTITULO_POSICION = "Dónde queda esta valuación"

#: Las tres relaciones posibles entre el rango de la valuación y el panel. Se publican
#: TAL CUAL —por eso empiezan en mayúscula— y los tests las importan. Viven en
#: constantes y no dentro de una f-string: un literal partido por ancho de línea deja de
#: existir en el fuente aunque el valor sea correcto, y el test que lo busque falla —o pasa—
#: sin motivo.
FRASE_RANGO_POR_DEBAJO = (
    "Todo el rango de esta valuación queda por debajo del múltiplo mínimo observado en el panel")
FRASE_RANGO_POR_ENCIMA = (
    "Todo el rango de esta valuación queda por encima del múltiplo máximo observado en el panel")
FRASE_RANGO_SOLAPA = "El rango de esta valuación solapa con lo observado en el panel"

_BASES = {tx.BASE_CONTABLE: "contable", tx.BASE_VALOR_RAZONABLE: "valor razonable (NIIF 3)"}


def _pais(codigo: str) -> str:
    return tx.nombre_de_pais(codigo)


@dataclass(frozen=True)
class PosicionFrenteAlPanel:
    """La relación entre el rango P/B de la valuación y el panel, COMPUTADA."""

    pb_bajo: float
    pb_alto: float
    #: Todo el rango por debajo del mínimo observado.
    por_debajo: bool
    #: Todo el rango por encima del máximo observado.
    por_encima: bool
    #: Ni una cosa ni la otra: el rango y el panel se cruzan en algún punto.
    solapa: bool
    mediana_dentro_del_rango: bool
    #: La mediana queda por encima del extremo favorable (la valuación es más baja que lo
    #: que se pagó en el caso típico) o por debajo del adverso.
    mediana_por_encima_del_rango: bool
    mediana_por_debajo_del_rango: bool
    #: Distancia del extremo favorable a la mediana, en veces el libro. Positiva si la
    #: mediana está por encima.
    distancia_favorable_a_mediana: float
    distancia_adverso_a_mediana: float


def posicion_frente_al_panel(pb_bajo: float, pb_alto: float,
                             r: tx.ResumenDelPanel) -> PosicionFrenteAlPanel:
    """Dónde cae el rango [pb_bajo, pb_alto] contra el panel. Se computa; la prosa copia."""
    por_debajo = pb_alto < r.minimo
    por_encima = pb_bajo > r.maximo
    return PosicionFrenteAlPanel(
        pb_bajo=pb_bajo, pb_alto=pb_alto,
        por_debajo=por_debajo, por_encima=por_encima,
        solapa=not (por_debajo or por_encima),
        mediana_dentro_del_rango=pb_bajo <= r.mediana <= pb_alto,
        mediana_por_encima_del_rango=r.mediana > pb_alto,
        mediana_por_debajo_del_rango=r.mediana < pb_bajo,
        distancia_favorable_a_mediana=round(r.mediana - pb_alto, 4),
        distancia_adverso_a_mediana=round(r.mediana - pb_bajo, 4),
    )


def prosa_de_la_posicion(pos: PosicionFrenteAlPanel, r: tx.ResumenDelPanel) -> str:
    """La lectura de la posición, con la relación ya computada y las cifras que la sostienen.

    Dice qué supuesto implica cada caso —igual que la sección de decisión—, y nunca que el
    modelo esté bien o mal: el panel son otras entidades, otras jurisdicciones y otros
    años, y esta valuación no lo usa para producir el valor.
    """
    cifras = (f"El múltiplo implícito de esta valuación va de **{pos.pb_bajo:.2f}×** a "
              f"**{pos.pb_alto:.2f}×**; el panel observa una mediana de **{r.mediana:.2f}×** "
              f"entre **{r.minimo:.2f}×** y **{r.maximo:.2f}×**.")
    if pos.por_debajo:
        lectura = (
            f"**{FRASE_RANGO_POR_DEBAJO}**: el "
            f"extremo favorable queda **{abs(pos.distancia_favorable_a_mediana):.2f}×** por "
            "debajo de la mediana. Quien pagara por esta entidad lo que el panel muestra "
            "estaría afirmando un ROE mayor o un costo de capital menor que los de acá, y "
            "esa afirmación se discute con evidencia, no con el panel.")
    elif pos.por_encima:
        lectura = (
            f"**{FRASE_RANGO_POR_ENCIMA}**: el "
            f"extremo adverso queda **{abs(pos.distancia_adverso_a_mediana):.2f}×** por "
            "encima de la mediana. Un comprador que pagara dentro de este rango estaría "
            "pagando más de lo que se pagó por cualquier banco del panel, o sea afirmando un "
            "exceso de retorno que ninguna transacción observada respaldó.")
    else:
        if pos.mediana_dentro_del_rango:
            mediana = ("la mediana del panel **cae dentro del rango**: el caso típico "
                       "observado es uno de los supuestos que esta valuación admite.")
        elif pos.mediana_por_encima_del_rango:
            mediana = (f"la mediana del panel queda **{abs(pos.distancia_favorable_a_mediana):.2f}×** "
                       "por encima del extremo favorable: en el caso típico se pagó más de lo "
                       "que el modelo sostiene con su supuesto más favorable.")
        else:
            mediana = (f"la mediana del panel queda **{abs(pos.distancia_adverso_a_mediana):.2f}×** "
                       "por debajo del extremo adverso: en el caso típico se pagó menos de lo "
                       "que el modelo sostiene incluso con su supuesto más adverso.")
        lectura = f"**{FRASE_RANGO_SOLAPA}**, y {mediana}"
    return f"{cifras}\n\n{lectura}"


def _fila(t: tx.Transaccion) -> str:
    pb = t.pb_recomputado
    return (f"| {t.anio} | {t.comprador} | {t.adquirida} | {_pais(t.pais)} | "
            f"{pb:.2f}× | {_BASES.get(t.base, t.base)} | {t.periodo_libro or '—'} |"
            if pb is not None else
            f"| {t.anio} | {t.comprador} | {t.adquirida} | {_pais(t.pais)} | — | "
            f"{_BASES.get(t.base, t.base)} | {t.periodo_libro or '—'} |")


def _ordenados(casos: Sequence[tx.Transaccion]) -> List[tx.Transaccion]:
    return sorted(casos, key=lambda t: (-t.anio, t.comprador))


def contraste_de_mercado(lec: Lectura, panel: Sequence[tx.Transaccion] = tx.PANEL, *,
                         con_anexo: bool) -> str:
    """La sección: tabla de comparables, resumen computado, posición del rango, y lo que el
    panel NO permite afirmar. `con_anexo` dice si el nivel trae el anexo con vías y
    descartes, para que el puntero apunte a donde corresponde."""
    estado = tx.estado(panel)
    if not estado.abierto:
        # El gate se consulta antes, no después. Con el panel corto la sección no publica
        # una tabla de tres casos como si fuera un mercado: declara la brecha con su motivo.
        return (
            "**La vista de fusiones y adquisiciones está cerrada, y se dice por qué.** "
            f"{estado.motivo}\n\n"
            "Mientras el gate no abra, esta valuación no se sitúa contra precios pagados: "
            "el rango se publica con sus supuestos y su sensibilidad, sin referencia de "
            "mercado.")

    r = tx.resumen(panel)
    if r is None:  # no puede pasar con el gate abierto; se declara igual, no se inventa
        return ("**La vista de fusiones y adquisiciones está cerrada.** " + estado.motivo)
    comparables = _ordenados([t for t in panel if t.comparable])
    otros = _ordenados([t for t in panel if t.verificable and not t.comparable])
    c = tx.contraste_del_modelo(panel)
    anios = [t.anio for t in comparables]
    paises = sorted({_pais(t.pais) for t in comparables})

    intro = (
        "**Enfoque de mercado, como contraste y no como método.** Una valuación se sitúa "
        "contra lo que alguien PAGÓ. El panel de transacciones bancarias del Caribe reúne "
        f"**{estado.n_verificables} operaciones con las dos puntas publicadas** —precio y "
        f"denominador—, de las cuales **{r.n} están sobre patrimonio contable**, que es la "
        "base contra la que valúa el Excess Return y la única que entra a la misma tabla. "
        f"Son {r.n} comparables en {len(paises)} jurisdicciones "
        f"({', '.join(paises)}) entre {min(anios)} y {max(anios)}. El panel no se usa para "
        "producir el valor: sitúa el rango de salida y nada más. "
        + _base_del_panel(comparables))

    filas = "\n".join(_fila(t) for t in comparables)
    tabla = (
        f"### {SUBTITULO_COMPARABLES}\n\n"
        "| Año | Comprador | Adquirida | País | P/B | Base | Corte del libro |\n"
        "|---|---|---|---|---|---|---|\n"
        f"{filas}\n\n"
        f"**Mediana {r.mediana:.2f}×**, mínimo {r.minimo:.2f}× y máximo {r.maximo:.2f}× sobre "
        f"{r.n} comparables. Cada múltiplo se recomputa desde sus insumos —precio, "
        "patrimonio al corte, tipo de cambio del mes y fracción comprada— y el corte del "
        "libro es el último publicado antes de la operación. Un múltiplo por debajo de 1.0× "
        "existe y está en la tabla: un panel que solo mirara hacia arriba estaría sesgado "
        "por selección.")

    pos = posicion_frente_al_panel(lec.pb_bajo, lec.pb_alto, r)
    posicion = f"### {SUBTITULO_POSICION}\n\n{prosa_de_la_posicion(pos, r)}"

    if otros:
        filas_otros = "\n".join(_fila(t) for t in otros)
        otra_base = (
            f"### {SUBTITULO_OTRA_BASE}\n\n"
            + ("Hay una operación más con las dos puntas publicadas cuyo denominador son "
               if len(otros) == 1 else
               f"Hay {len(otros)} operaciones más con las dos puntas publicadas cuyo "
               "denominador son ")
            + "los activos netos identificables a **valor razonable** de la NIIF 3: lo que "
            "el COMPRADOR reconoce, no lo que el vendedor tenía en libros. Son datos "
            "verificables y no son un P/B —en una de ellas el intangible reconocido en la "
            "adquisición es el 62 % del denominador—, así que no entran ni a la tabla ni a "
            "la mediana. Se listan para que no desaparezcan.\n\n"
            "| Año | Comprador | Adquirida | País | Precio / activos netos | Base | Corte |\n"
            "|---|---|---|---|---|---|---|\n"
            f"{filas_otros}")
    else:
        otra_base = ""

    limites = (
        "**El panel abre la vista de mercado y no valida el modelo.** Contrastar ESTE "
        "modelo exigiría valuar cada adquirida con el Excess Return a la fecha de su "
        "operación y comparar ese valor con el precio, y para eso hace falta su historia de "
        f"ROE y patrimonio: la tenemos para {c.n_valuables} de los {c.n_comparables} "
        "comparables, porque el balance por entidad solo se ingiere de República "
        "Dominicana. Por eso la sección de limitaciones sigue diciendo que esta valuación no "
        "está contrastada contra precios pagados.\n\n"
        f"Se relevaron además {len(tx.DESCARTADAS)} operaciones que no entran al panel "
        "—anunciadas sin monto, no consumadas, disoluciones, fusiones entre iguales— y "
        f"quedan {len(tx.VIAS_ABIERTAS)} vías abiertas con lo que falta nombrado en cada "
        "una. "
        + ("El anexo las lista una por una, con su motivo, y con lo que cada comparable "
           "NO permite afirmar." if con_anexo else
           "El Deep Dive las lista una por una, con su motivo, y con lo que cada comparable "
           "NO permite afirmar."))

    partes = [intro, tabla, posicion]
    if otra_base:
        partes.append(otra_base)
    partes.append(limites)
    return "\n\n".join(partes)


def _base_del_panel(comparables: Sequence[tx.Transaccion]) -> str:
    """Que el panel esté en la misma base que el modelo —control— se COMPUTA de las
    fracciones compradas, no se afirma: si entra un comparable minoritario, la frase cambia
    sola y deja de decir «misma base»."""
    n_todo = sum(1 for t in comparables if t.porcentaje >= 1.0)
    minimo = min(t.porcentaje for t in comparables)
    if minimo < 0.5:
        return (f"Ojo con la base: {n_todo} de las {len(comparables)} operaciones compran "
                f"el 100 % y la fracción mínima es {minimo * 100:.0f} %, así que no todo el "
                "panel está en la misma base de control que este rango.")
    return (f"Son operaciones de control: {n_todo} de las {len(comparables)} compran el "
            f"100 % y la fracción mínima es {minimo * 100:.0f} %, así que el múltiplo pagado "
            "está en la misma base que este rango — el de la entidad entera.")


def supuestos_y_sensibilidad(lec: Lectura) -> str:
    """Los PARÁMETROS que produjeron esta cifra, con su procedencia, y qué la mueve.

    Es la sección que un comité usa para discutir el número: cada fila es un supuesto que se
    puede rebatir. Todo sale de la `Lectura` —los términos del Ke viajan en el payload— y
    nada se lee de una constante al renderizar: un informe en caché dice la beta con la que
    se valuó, no la que rige hoy.
    """
    rf, beta, erp = lec.rf_pct, lec.beta, lec.erp
    filas = [
        ("Rf · curva soberana en pesos, más de dos años",
         f"{rf[0]:.2f} % – {rf[1]:.2f} %",
         f"dato: {lec.n_observaciones_rf} observación(es) del cuadro V.1 del BCRD"),
        ("β de equity, por tipo de entidad", f"{beta[0]:.2f} – {beta[1]:.2f}",
         "rúbrica: bancos cotizados latinoamericanos, sin desapalancar"),
        ("ERP · prima de riesgo de mercado", f"{erp[0]:.2f} % – {erp[1]:.2f} %",
         "rúbrica: renta variable latinoamericana"),
        ("Ke = Rf + β × ERP", f"{lec.ke_bajo_pct:.2f} % – {lec.ke_alto_pct:.2f} %",
         f"{lec.fraccion_de_rubrica * 100:.0f} % del Ke es rúbrica"),
        ("ROE proyectado", f"{lec.roe_proyectado_pct:.2f} %",
         "mediana de los últimos cuatro cortes con ROE de doce meses sobre patrimonio de "
         "apertura — mediana y no promedio, para que un corte atípico no arrastre la cifra"),
        ("Persistencia del exceso (ω)", f"{lec.persistencia:.3f}", "medida por tipo"),
        ("Retención de utilidades (b)", f"{lec.retencion:.2f}", "medida por tipo"),
        ("Crecimiento terminal (g)", f"{lec.g_terminal_pct:.2f} %",
         "ROE × b, con techo en el crecimiento nominal de la economía"),
    ]
    tabla = ("| Parámetro | Valor usado | Procedencia |\n|---|---|---|\n"
             + "\n".join(f"| {a} | {b} | {c} |" for a, b, c in filas))
    intro = (
        "**Estos son los supuestos con los que se produjo la cifra, tal cual se usaron.** "
        "Los que dicen «dato» se observaron; los que dicen «rúbrica» son supuestos "
        "declarados, y son los que un lector puede no compartir.")
    extremos = (
        f"**Sensibilidad al costo de capital.** En el extremo favorable del rango de `Ke` la "
        f"entidad vale **{lec.pb_alto:.2f}×** su libro; en el adverso, **{lec.pb_bajo:.2f}×**. "
        "Toda esa distancia la produce el costo de capital, que es el supuesto y no el dato.")
    if lec.cambia_de_signo:
        signo = (
            "**El spread cruza el cero dentro del rango.** No hay un movimiento que «dé "
            "vuelta» la lectura porque la lectura ya contiene los dos signos: lo que la "
            "resolvería es un ROE sostenido fuera del rango de `Ke`, o una curva en pesos que "
            "lo angoste.")
    else:
        margen = abs(_cuanto_falta_para_cambiar_de_signo(lec))
        signo = (
            f"**Cuánto falta para cambiar de signo: {margen:.2f} pp.** Un movimiento de esa "
            "magnitud en el costo de capital o en el ROE sostenido invierte la lectura. Es la "
            "cifra que hay que vigilar: la curva en pesos a más de dos años y la trayectoria "
            "del ROE sobre patrimonio de apertura.")
    return "\n\n".join([intro, tabla, extremos, signo])


# ── Conclusión y responsabilidad ─────────────────────────────────────────────────

FRASE_INDEPENDENCIA = (
    "**Independencia.** SDQ Consulting no tiene interés económico en la entidad valuada, no "
    "mantiene con ella una relación profesional vigente y sus honorarios no dependen del "
    "resultado de esta valuación.")
FRASE_RELACION_DECLARADA = (
    "**Relación declarada.** {relacion}. Esta valuación NO se presenta como independiente: el "
    "método y las cifras son los mismos que para cualquier otra entidad, y la relación se "
    "declara para que el lector la pese.")
FRASE_RESPONSABILIDAD = (
    "**Responsabilidad.** Emitido por **SDQ Consulting** a través de la plataforma SDQ·MIP, "
    "sin firmante personal: la firma es institucional. SDQ Consulting responde por el método "
    "y por la lectura; la prosa de este informe es computada de las cifras, sin intervención "
    "de un modelo de lenguaje, y cada cifra se puede reproducir con la información pública "
    "que la sección de fuentes nombra.")
FRASE_ALCANCE_NORMATIVO = (
    "**Alcance normativo.** No es una valuación bajo NIIF 13 ni bajo los International "
    "Valuation Standards, ni una tasación con efectos fiscales o regulatorios; es una opinión "
    "de valor por el enfoque de ingreso con supuestos declarados, para discusión de comité y "
    "encuadre de negociación.")
FRASE_SIN_CAMBIOS = ("no hay cambios de metodología registrados para este eje desde su "
                     "publicación")


def conclusion_y_responsabilidad(c: Optional["Cierre"], lec: Lectura) -> str:
    """La última sección: el valor en una línea y quién responde por él, con qué versión
    del método, con qué estado de validación y desde qué posición frente a la entidad."""
    if lec.cambia_de_signo:
        veredicto = ("el spread ROE − Ke cambia de signo dentro del rango de costo de capital, "
                     "así que crear o destruir valor depende de un supuesto que no se observa")
    elif lec.destruye_valor:
        veredicto = "la entidad destruye valor en todo el rango razonable de costo de capital"
    else:
        veredicto = "la entidad crea valor en todo el rango razonable de costo de capital"
    conclusion = (
        f"**Conclusión.** {lec.entidad}, con estados al **{lec.periodo}**: patrimonio contable "
        f"de **RD$ {lec.patrimonio_libro:,.0f}** y valor estimado entre **RD$ {lec.valor_bajo:,.0f}** "
        f"y **RD$ {lec.valor_alto:,.0f}** (**{lec.pb_bajo:.2f}× a {lec.pb_alto:.2f}×** el libro), "
        f"porque {veredicto}. El detalle está en la sección de conclusión de valor y los "
        "supuestos que lo sostienen, en la de supuestos y sensibilidad.")
    if c is None:
        return "\n\n".join([conclusion, FRASE_RESPONSABILIDAD, FRASE_ALCANCE_NORMATIVO])
    emision = (f"**Emisión.** Emitido el **{c.emitido_el}** con corte de información al "
               f"**{c.corte}**.")
    if c.metodologia_id:
        metodologia = (
            f"**Metodología vigente.** `{c.metodologia_id}` ({c.metodologia_fecha}): "
            f"{c.metodologia_titulo}. Es la última entrada del registro de cambios del eje al "
            "emitir; el registro completo, con qué cambió y por qué, está abierto en la "
            "plataforma (`/api/v1/products/methodology-changelog?sector=valuation`).")
    else:
        metodologia = f"**Metodología vigente.** Al emitir, {FRASE_SIN_CAMBIOS}."
    if c.validacion_aprobada:
        validacion = (f"**Estado de validación.** Validada contra {c.validacion_desenlace}; el "
                      "veredicto vigente se lee en la plataforma, no en este documento.")
    else:
        validacion = (f"**Estado de validación.** No contrastada contra {c.validacion_desenlace}: "
                      "el eje publica el modelo, sus supuestos y su sensibilidad, y el motivo "
                      "está en la sección de limitaciones.")
    posicion = (FRASE_RELACION_DECLARADA.format(relacion=c.relacion_declarada)
                if c.relacion_declarada else FRASE_INDEPENDENCIA)
    return "\n\n".join([conclusion, emision, metodologia, validacion, posicion,
                        FRASE_RESPONSABILIDAD, FRASE_ALCANCE_NORMATIVO])


def _un_parrafo(texto: str) -> str:
    """Un motivo con saltos de párrafo adentro se convierte en una sola viñeta: el
    renderizador parte las viñetas por línea, y un salto la cortaría en dos."""
    return " ".join(p.strip() for p in texto.split("\n") if p.strip())


def anexo_del_panel(panel: Sequence[tx.Transaccion] = tx.PANEL) -> str:
    """Vías abiertas, descartes con motivo, la discrepancia declarada y lo que cada
    comparable NO permite afirmar. Un panel chico sin explicación se lee como falta de
    trabajo; esto es el resultado del trabajo."""
    comparables = _ordenados([t for t in panel if t.comparable])
    caveats: List[str] = []
    for t in comparables:
        caveats.append(f"**{t.anio} · {t.comprador} → {t.adquirida}** — alcance: {t.alcance}.")
        caveats += [f"- {_un_parrafo(cv)}" for cv in t.caveats]
    vias = "\n".join(f"- **{n}** — {_un_parrafo(f)}" for n, f in tx.VIAS_ABIERTAS)
    descartes = "\n".join(f"- **{n}** — {_un_parrafo(m)}" for n, m in tx.DESCARTADAS)
    return (
        "### Lo que cada comparable NO permite afirmar\n\n"
        "Los caveats viajan con el dato: un múltiplo sin ellos se lee con más precisión de "
        "la que tiene.\n\n"
        + "\n".join(caveats) + "\n\n"
        f"### Vías abiertas ({len(tx.VIAS_ABIERTAS)})\n\n"
        "Operaciones donde falta UNA cosa concreta y se sabe cuál. No son descartes y no "
        "son casos: entran al panel el día que se cierre lo que falta.\n\n"
        f"{vias}\n\n"
        f"### Operaciones relevadas y descartadas ({len(tx.DESCARTADAS)})\n\n"
        f"{descartes}\n\n"
        "### Una discrepancia que se declara en vez de resolverse\n\n"
        f"{tx.DISCREPANCIA_RFHL}")
