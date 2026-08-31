"""La CAPACIDAD DE PAGO del deudor: qué puede sostener quien debe.

Tres lecturas de la misma pregunta, y las tres estaban en la base sin que ningún informe las
leyera — que es la forma silenciosa de no entregar un dato:

* **la inflación de SU canasta**, abierta por quintil de ingreso (BCRD). La del titular es un
  promedio de la economía; la que aprieta a un hogar endeudado es la suya.
* **el piso de ingreso**, el salario mínimo mensual por tamaño de empresa y área (MHE vía
  datos.gob.do). Es mensual, así que cada ajuste aparece como un ESCALÓN fechado.
* **la formalidad del empleo**, de la ENCFT trimestral del BCRD. Un ocupado informal no tiene
  ingreso verificable, y el crédito de consumo se origina contra ingreso declarado.

Para qué sirven en banca. El crédito de consumo es el rubro más grande del sistema —26,6% del
crédito al cierre de marzo de 2026— y se concentra en los quintiles bajos. Estas tres fijan si
ese deudor puede pagar, y ninguna aparece en un estado financiero.

Qué hace que esto no lo pueda producir un banco. Los datos son públicos: cualquiera los baja.
Lo que no puede hacer un banco es CRUZARLOS con la composición sectorial del libro de las
noventa y una entidades restantes — decir «tu consumo es el 41,6% de tu cartera, su mora corre
2,7 puntos sobre la del resto del sistema, y en la ventana medida la canasta del quintil 1
subió 6,1 puntos más que la del quintil 5». Cada serie sola es un dato público; junto al mapa
sectorial es una atribución.

Doctrina aplicada. Las relaciones —la brecha entre quintiles, el crédito promedio medido en
salarios mínimos— se COMPUTAN acá y el modelo las copia. La serie del IPC es un ÍNDICE, así
que la acumulación se calcula sobre índices y nunca sumando variaciones. Y lo que falta se
DECLARA: media lectura parece una medición y no lo es.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: Las cinco series de ÍNDICE del IPC por quintil de ingreso (BCRD, base 2019-2020).
#: Son índices y no tasas a propósito: la planilla trae además cinco columnas de tasa que la
#: inferencia nombra por COORDENADA (`..._c5`, `..._c7`) sin decir de qué quintil son, y una
#: tasa que no nombra su población es exactamente lo que no se debe servir. La variación se
#: deriva del índice, que sí viaja con su sujeto en la clave.
_PREFIJO = "bcrd.xls.ipc_quintiles_base_2019_2020.quintil_"
QUINTILES: Tuple[int, ...] = (1, 2, 3, 4, 5)

#: Mínimo de meses para afirmar una acumulación. Con menos, la «brecha» es ruido de dos
#: lecturas y no una trayectoria.
_MIN_MESES = 12


def _serie(db: Session, quintil: int, hasta: str) -> List[Tuple[str, float]]:
    """Los puntos (período, índice) del quintil, hasta *hasta* inclusive.

    El corte es el del INFORME: una serie que llegue a julio no puede aparecer en un informe
    de marzo, que es el mismo motivo por el que el telón macro se poda por fecha."""
    from modules.macro_monitor.models.models import MacroSeries

    filas = (db.query(MacroSeries.period, MacroSeries.value)
             .filter(MacroSeries.series_code == f"{_PREFIJO}{quintil}",
                     MacroSeries.value.isnot(None),
                     MacroSeries.period <= hasta)
             .order_by(MacroSeries.period)
             .all())
    return [(str(p), float(v)) for p, v in filas]


def _acumulada(puntos: List[Tuple[str, float]]) -> Optional[float]:
    """Variación acumulada del ÍNDICE entre el primer y el último punto, en %.

    Sobre índices, nunca sumando variaciones mensuales: sumar tasas subestima la
    acumulación por el interés compuesto que ignora, y sobre cinco años la diferencia deja
    de ser cosmética."""
    if len(puntos) < _MIN_MESES:
        return None
    base = puntos[0][1]
    if base <= 0:
        return None
    return round((puntos[-1][1] / base - 1.0) * 100.0, 2)


def inflacion_por_quintil(db: Session, corte: date) -> Optional[Dict[str, Any]]:
    """La inflación acumulada por quintil de ingreso hasta *corte*, con su brecha.

    Devuelve ``None`` cuando falta algún quintil: la lectura es la COMPARACIÓN entre el
    primero y el quinto, y con cuatro de cinco no se puede afirmar que el primero sea el
    extremo. Declarar la brecha es mejor que publicar media."""
    hasta = f"{corte.year}-{corte.month:02d}"
    series = {q: _serie(db, q, hasta) for q in QUINTILES}
    medidos = {q: _acumulada(p) for q, p in series.items()}
    faltan = [q for q, v in medidos.items() if v is None]
    if faltan:
        logger.info("Inflación por quintil omitida hasta %s: sin serie suficiente en %s",
                    hasta, faltan)
        return None
    # Estrechado UNA vez, acá: pasado este punto no hay huecos, y cada lectura de abajo no
    # tiene que volver a defenderse de un `None` que ya se descartó.
    acum: Dict[int, float] = {q: v for q, v in medidos.items() if v is not None}

    primero, ultimo = series[1][0][0], series[1][-1][0]
    q1, q5 = acum[1], acum[5]
    return {
        "desde": primero,
        "hasta": ultimo,
        "meses": len(series[1]),
        # El SUJETO en la clave: es la inflación acumulada de la canasta de CADA quintil de
        # ingreso, no la del índice general ni la de un sector.
        "inflacion_acumulada_por_quintil_de_ingreso_pct": {
            f"quintil_{q}": v for q, v in acum.items()},
        # LA RELACIÓN SE COMPUTA ACÁ. El modelo la copia; derivarla de dos porcentajes es
        # cómo se invierte una dirección.
        "brecha_quintil_1_menos_quintil_5_pp": round(q1 - q5, 2),
        "quintil_mas_golpeado": f"quintil_{max(acum, key=lambda q: acum[q])}",
        "que_es": ("inflación acumulada de la canasta de cada quintil de ingreso, medida "
                   "sobre el índice del BCRD (base 2019-2020) entre los dos extremos de la "
                   "ventana; una brecha positiva significa que la canasta del quintil más "
                   "pobre subió MÁS que la del más rico"),
        "por_que_importa_en_credito": (
            "el crédito de consumo se concentra en los quintiles de menor ingreso, así que "
            "su capacidad de pago la fija esta inflación y no la del índice general"),
    }


# ── El PISO de ingreso: el salario mínimo ────────────────────────────────────────────
#
# El salario mínimo dominicano no es UNO: son DIEZ combinaciones de tamaño de empresa y área,
# y varias llevan años congeladas —«zona franca en áreas geográficas deprimidas» sigue en
# RD$3.600 desde julio de 2006, y el Gobierno Central en RD$10.000 desde abril de 2019—.
# Elegir una al azar publicaría como piso vigente un número que nadie cobra hoy, así que la
# referencia se DECLARA y se comprueba que esté viva.
#
# Se toma la empresa GRANDE del sector privado no sectorizado (RD$27.989 desde abril de 2025):
# es el techo del piso legal y la referencia contra la que se lee un crédito de consumo de
# banca múltiple. La clave lo nombra — un salario mínimo sin su categoría es un número sin
# sujeto.
#
# La clave es la que produce `social_sync._tema_salario` sobre la fuente, no una inventada:
# la primera versión de esta línea decía `sm_empresa_grande_no_sectorizado` —plausible y
# falsa— y la lectura entera habría devuelto `None` en silencio, que es el defecto que este
# repo tiene nombrado: un binding a una serie inexistente no falla, DESAPARECE. Lo vigila
# `test_la_referencia_del_salario_EXISTE_en_la_fuente`.
_TEMA_SALARIO_REFERENCIA = "sm_empresa_grande_empresas_del_sector_no_secto"

#: Meses sin ajuste a partir de los cuales la referencia deja de describir el presente. Dos
#: años es más de lo que cualquier ajuste dominicano ha tardado en la serie observada.
_MESES_PARA_CONGELADA = 24


def _puntos_sociales(db: Session, tema: str, hasta: str) -> List[Tuple[str, float]]:
    from modules.social_dev.models.models import SocialIndicator

    filas = (db.query(SocialIndicator.period, SocialIndicator.value)
             .filter(SocialIndicator.theme == tema,
                     SocialIndicator.value.isnot(None),
                     SocialIndicator.period <= hasta)
             .order_by(SocialIndicator.period)
             .all())
    return [(str(p), float(v)) for p, v in filas]


def _meses_entre(desde: str, hasta: str) -> Optional[int]:
    try:
        ay, am = (int(x) for x in desde.split("-")[:2])
        by, bm = (int(x) for x in hasta.split("-")[:2])
    except (ValueError, IndexError):
        return None
    return (by - ay) * 12 + (bm - am)


def salario_minimo(db: Session, corte: date) -> Optional[Dict[str, Any]]:
    """El piso de ingreso vigente al corte, con la fecha de su último ajuste.

    La fecha del ajuste no es decoración: una serie escalonada repite su valor hasta el
    próximo cambio, así que una categoría abandonada se ve idéntica a una vigente. Sin
    declararla, el informe afirmaría como piso de hoy un número de hace veinte años."""
    hasta = f"{corte.year}-{corte.month:02d}"
    puntos = _puntos_sociales(db, _TEMA_SALARIO_REFERENCIA, hasta)
    if not puntos:
        logger.info("Salario mínimo omitido hasta %s: sin serie para %s",
                    hasta, _TEMA_SALARIO_REFERENCIA)
        return None

    vigente = puntos[-1][1]
    # El último ESCALÓN: el primer período en que la serie alcanzó su valor actual.
    ultimo_ajuste = next((p for p, v in puntos if v == vigente), puntos[-1][0])
    antiguedad = _meses_entre(ultimo_ajuste, puntos[-1][0])
    return {
        # El SUJETO en la clave: es el piso de UNA categoría, no «el salario mínimo».
        "salario_minimo_mensual_de_empresa_grande_no_sectorizada_rd": round(vigente, 2),
        "ultimo_ajuste": ultimo_ajuste,
        "meses_sin_ajuste": antiguedad,
        "congelada": bool(antiguedad is not None and antiguedad >= _MESES_PARA_CONGELADA),
        "que_es": ("el salario mínimo mensual de la empresa grande del sector privado no "
                   "sectorizado — el techo del piso legal, y la referencia contra la que se "
                   "lee un crédito de consumo de banca múltiple; hay once combinaciones de "
                   "tamaño y área y varias llevan años congeladas"),
    }


def credito_en_salarios_minimos(credito_promedio: Optional[float],
                                salario: Optional[Dict[str, Any]]) -> Optional[float]:
    """Cuántos salarios mínimos mensuales equivale un crédito promedio.

    Es una referencia de ESCALA, no una afirmación sobre el deudor: nadie sostiene que quien
    tomó ese crédito gane el mínimo. Sirve para leer un monto contra el piso de ingreso de la
    economía en vez de contra nada, y para comparar la entidad con el resto del sistema —que
    es la mitad que un banco no puede computar."""
    if not credito_promedio or not salario:
        return None
    piso = salario.get("salario_minimo_mensual_de_empresa_grande_no_sectorizada_rd")
    if not piso:
        return None
    return round(float(credito_promedio) / float(piso), 1)


# ── La FORMALIDAD del empleo ─────────────────────────────────────────────────────────

#: Las series laborales que el informe lee, con el nombre que llevan en el contexto.
#:
#: SU1 y SU4 van LAS DOS. El BCRD publica cuatro medidas de subutilización y durante meses se
#: citó solo SU1 —la desocupación abierta—: 4,95% contra 10,55% de SU4 al primer trimestre de
#: 2026, menos de la mitad de la holgura real. La diferencia es justo la población de crédito
#: de consumo: el subocupado por horas tiene empleo e ingreso INSUFICIENTE, no aparece en SU1
#: y sí aparece en la mora. Servir solo la angosta no es un recorte, es otra conclusión.
_TEMAS_LABORALES = {
    "informality_rate_trimestral": "ocupacion_informal_pct",
    "unemployment_rate_trimestral": "desocupacion_abierta_su1_pct",
    "underutilization_su4_trimestral": "subutilizacion_amplia_su4_pct",
    "underemployment_rate_trimestral": "subocupacion_por_horas_pct",
    "employment_rate_trimestral": "tasa_de_ocupacion_pct",
}


def mercado_laboral(db: Session, corte: date) -> Optional[Dict[str, Any]]:
    """Desocupación, ocupación e informalidad al TRIMESTRE del corte.

    Trimestral y no anual a propósito: el crédito se mide por trimestre, y leer el deterioro
    de una cartera contra un promedio anual del mercado laboral compara dos cosas que no
    ocurrieron en la misma ventana. La serie anual existe y sostiene otros ejes; acá no sirve.
    """
    trimestre = f"{corte.year}-Q{(corte.month - 1) // 3 + 1}"
    out: Dict[str, Any] = {}
    for tema, clave in _TEMAS_LABORALES.items():
        puntos = [(p, v) for p, v in _puntos_sociales(db, tema, trimestre)
                  if p.startswith(str(corte.year)) or p < trimestre]
        if puntos:
            out[clave] = round(puntos[-1][1], 2)
            out.setdefault("trimestre", puntos[-1][0])
    if "ocupacion_informal_pct" not in out:
        logger.info("Mercado laboral omitido hasta %s: sin informalidad trimestral",
                    trimestre)
        return None
    # LA RELACIÓN SE COMPUTA ACÁ: cuánta holgura laboral queda fuera de la medida angosta.
    # Es la resta que el modelo haría mal —o no haría— y es el punto entero del bloque.
    ancha = out.get("subutilizacion_amplia_su4_pct")
    angosta = out.get("desocupacion_abierta_su1_pct")
    if ancha is not None and angosta is not None:
        out["holgura_que_SU1_no_ve_pp"] = round(ancha - angosta, 2)
    out["por_que_importa_en_credito"] = (
        "un ocupado informal no tiene ingreso verificable, y el crédito de consumo se "
        "origina contra ingreso declarado: la informalidad acota a qué parte de la "
        "población se le puede prestar con documentación y a qué parte no. La "
        "subutilización amplia (SU4) suma al desocupado abierto el subocupado por horas y "
        "la fuerza de trabajo potencial: es gente con empleo e ingreso insuficiente, que no "
        "aparece en la desocupación y sí en la mora de consumo")
    return out


# ── Lo que CUESTA la canasta, en pesos ───────────────────────────────────────────────
#
# El IPC dice cuánto SUBIÓ la canasta de un hogar; esto dice cuánto CUESTA. Contra el piso de
# ingreso da la frase que no necesita índices —«el salario mínimo cubre el 94% de la canasta
# del quintil más pobre»— y el documento metodológico del BCRD señala esa comparación como la
# referencia de las discusiones sobre el salario mínimo del sector privado no sectorizado.
_PREFIJO_CANASTA = "bcrd.xls.costo_canasta_quintiles_base_2019_2020.quintil_"


def costo_de_la_canasta(db: Session, corte: date) -> Optional[Dict[str, Any]]:
    """Lo que cuesta al mes la canasta de cada quintil, en RD$ corrientes."""
    from modules.macro_monitor.models.models import MacroSeries

    hasta = f"{corte.year}-{corte.month:02d}"
    costo: Dict[int, float] = {}
    periodo = ""
    for q in QUINTILES:
        fila = (db.query(MacroSeries.period, MacroSeries.value)
                .filter(MacroSeries.series_code == f"{_PREFIJO_CANASTA}{q}",
                        MacroSeries.value.isnot(None),
                        MacroSeries.period <= hasta)
                .order_by(MacroSeries.period.desc())
                .first())
        if fila is None:
            logger.info("Costo de canasta omitido hasta %s: falta el quintil %s", hasta, q)
            return None
        periodo, costo[q] = str(fila[0]), round(float(fila[1]), 2)
    return {
        "periodo": periodo,
        # El SUJETO en la clave: es el costo mensual de la canasta de CADA quintil de
        # ingreso, no el de una canasta única ni el de una región.
        "costo_mensual_de_la_canasta_por_quintil_de_ingreso_rd": {
            f"quintil_{q}": v for q, v in costo.items()},
        "que_es": ("lo que cuesta al mes, en RD$ corrientes, la canasta de consumo de un "
                   "hogar de cada quintil de ingreso, según el BCRD"),
    }


def cobertura_del_piso_de_ingreso(salario: Optional[Dict[str, Any]],
                                  canasta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Qué porción de la canasta de cada quintil cubre el piso de ingreso.

    LA RELACIÓN SE COMPUTA ACÁ. Es una división de dos cifras que el informe también sirve,
    y pedirle al modelo que la haga es pedirle que invente el resultado: ya pasó con una
    suma de dos porcentajes que vetó un informe entero.

    Una cobertura por debajo de 100 significa que un hogar de ese quintil, con un solo
    ingreso al piso legal, NO llega a su propia canasta. No dice que ese hogar tenga ese
    ingreso: dice qué alcanza el piso, que es lo que fija el suelo de la capacidad de pago."""
    if not salario or not canasta:
        return None
    piso = salario.get("salario_minimo_mensual_de_empresa_grande_no_sectorizada_rd")
    costos = canasta.get("costo_mensual_de_la_canasta_por_quintil_de_ingreso_rd") or {}
    if not piso or not costos:
        return None
    cobertura = {k: round(float(piso) / float(v) * 100.0, 1)
                 for k, v in costos.items() if v}
    if not cobertura:
        return None
    return {
        "cobertura_de_la_canasta_por_el_salario_minimo_pct": cobertura,
        "quintiles_que_el_piso_NO_cubre": sorted(k for k, v in cobertura.items() if v < 100),
        "lectura": ("porcentaje de la canasta mensual de cada quintil que alcanza a cubrir "
                    "un salario mínimo de empresa grande no sectorizada; por debajo de 100 "
                    "el piso legal no llega a esa canasta"),
    }


def capacidad_de_pago(db: Session, corte: date) -> Optional[Dict[str, Any]]:
    """Las tres lecturas juntas. Devuelve ``None`` solo si NINGUNA está disponible: cada
    una responde algo distinto y media respuesta es mejor que ninguna, siempre que se
    declare cuál falta —que es lo que hace la ausencia de la clave—."""
    bloque: Dict[str, Any] = {}
    for clave, fn in (("inflacion_del_deudor", inflacion_por_quintil),
                      ("salario_minimo", salario_minimo),
                      ("costo_de_la_canasta", costo_de_la_canasta),
                      ("mercado_laboral", mercado_laboral)):
        try:
            valor = fn(db, corte)
        except Exception:  # noqa: BLE001 — ninguna lectura tumba al informe
            logger.exception("Capacidad de pago: falló %s al %s", clave, corte)
            valor = None
        if valor:
            bloque[clave] = valor
    # La relación entre las dos: se computa acá y el modelo la copia. Solo existe si están
    # las dos patas; con una sola no hay cociente, y media respuesta parece una medición.
    cobertura = cobertura_del_piso_de_ingreso(bloque.get("salario_minimo"),
                                              bloque.get("costo_de_la_canasta"))
    if cobertura:
        bloque["cobertura_del_piso_de_ingreso"] = cobertura
    return bloque or None
