"""El libro de crédito del SISTEMA abierto por sector, y la posición de cada entidad en él.

Qué contesta y por qué no puede contestarlo un banco solo. La pregunta de un comité de
crédito es «mi cartera de construcción se deterioró: ¿es mi originación o es el sector?».
Para responderla hay que comparar la mora de la entidad en ese sector contra la del RESTO
del sistema en el mismo sector, y eso exige el libro de las otras noventa y una entidades.
Un banco tiene una sola fila del cubo de la SIB: la suya.

Tres lecturas, en este orden:

1. **El sistema por sector** — cuánto se presta a cada sector, con qué mora y con qué mora
   TEMPRANA (31-90 días), que es la señal adelantada.
2. **La posición de la entidad** — su peso en cada sector contra el peso que ese sector
   tiene en el sistema. Estar concentrado no es un defecto: es una decisión que se lee
   contra lo que hace el resto.
3. **La atribución** — la brecha entre la mora de la entidad y la del sector separa lo
   IDIOSINCRÁTICO de lo COMPARTIDO. Es la única de las tres que exige el panel completo, y
   es la que vale.

Contra QUÉ se compara. Contra el RESTO del sistema, no contra el sistema entero. Con el
total, una entidad grande se compara en buena medida CONTRA SÍ MISMA: su propia mora entra
en el promedio que debía servirle de referencia y lo arrastra hacia ella, de modo que
cuanto más grande es la entidad más pequeña sale su brecha. El sesgo va siempre en la
misma dirección —hacia «acá no pasa nada»— y es máximo justo en las entidades cuya
originación más importa. Por eso `_agregar` se computa una sola vez sobre todas las celdas
y la referencia de la entidad se obtiene RESTÁNDOLE la suya.

La tasa es un PROMEDIO PONDERADO, y no se promedia. La SIB publica `tasaPorDeuda` como la
suma de tasa × saldo (su *Catálogo de Indicadores Financieros* v3.0 lo define: la variable
de ponderación es el saldo adeudado), y persistimos el cociente por celda. Agregar celdas
exige RE-PONDERAR por `deuda_con_tasa`: el promedio simple de los cocientes le da a una
celda de un millón el mismo voto que a una de diez mil millones. Las celdas sin tasa creíble
salen del numerador Y del denominador — si quedaran en el denominador, la tasa agregada se
diluiría hacia cero por celdas que nunca aportaron.

Doctrina aplicada. Las relaciones se COMPUTAN acá y el modelo las copia; no se le pide que
derive una dirección. Cada cuota nombra su población en la clave (`peso_en_su_cartera_pct`
vs `cuota_del_sector_pct`) porque son dos denominadores distintos y el modelo reatribuye al
sujeto más cercano. Y solo se ordena lo comparable: una entidad que no presta a un sector NO
entra en la mora de ese sector con un cero — no prestar no es prestar bien.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank
from shared.reference.cartera_agregacion import (_agregar, _medidas, _pct, _restar,
                                                 _sumar, _tasa, _vacio)
from shared.narrative.derived import concentracion_top_n
from shared.reference.cartera_sectorial import CarteraSectorial

logger = logging.getLogger(__name__)

# Debajo de este monto la mora de una celda es ruido: un solo crédito la mueve decenas de
# puntos. No se oculta la celda —desaparecer sin aviso es peor— pero no se rankea ni se
# narra como señal.
MATERIALIDAD_DEUDA = 1_000_000.0

# Cuánto tiene que separarse la mora de la entidad de la del sector para llamarla suya. Por
# debajo, la diferencia no sostiene una afirmación de originación.
BRECHA_MATERIAL_PP = 1.0


def _celdas(db: Session, corte: date) -> List[CarteraSectorial]:
    return (db.query(CarteraSectorial)
            .filter(CarteraSectorial.period_end == corte)
            .all())


def _agregar_por(celdas: List[CarteraSectorial], clave) -> Dict[str, Dict[str, Any]]:
    """El mismo acumulador, agrupando por otra dimensión del cubo.

    `_agregar` agrupa por sector porque es la lectura que abre el informe. Pero la celda del
    cubo es sector × PROVINCIA, y la provincia se estaba agregando hasta hacerla desaparecer:
    la tabla existía en la base y no salía por ninguna superficie. Con esta función la misma
    aritmética —y las mismas reglas de la tasa ponderada— sirven las dos lecturas."""
    out: Dict[str, Dict[str, Any]] = {}
    for c in celdas:
        k = clave(c)
        if not k:
            continue
        _sumar(out.setdefault(str(k), _vacio()), c)
    return out


def _por_provincia(celdas: List[CarteraSectorial], total: float) -> List[Dict[str, Any]]:
    """El crédito abierto por PROVINCIA, con las medidas que la provincia sí decide.

    Qué se sirve y qué no. Van la exposición, la mora, la mora temprana, la tasa y la
    garantía: todas se computan sobre la celda y significan lo mismo a este nivel. NO va el
    número de sectores como si fuera una medida de diversificación —una provincia con dos
    sectores puede estar mejor diversificada por monto que otra con diez— así que se sirve el
    conteo con su nombre y nada más.
    """
    # La región es un atributo de la provincia, no una medida: se toma la primera no vacía.
    region_de: Dict[str, Any] = {}
    for c in celdas:
        if c.region and str(c.provincia) not in region_de:
            region_de[str(c.provincia)] = str(c.region)
    filas = []
    for provincia, acc in _agregar_por(celdas, lambda c: c.provincia).items():
        # «SIN PROVINCIA» NO se descarta: es una porción real del libro cuyo rótulo la
        # fuente no trae, y esconderla haría que las cuotas no sumaran cien sin decir por qué.
        fila = {
            "provincia": provincia,
            # La región TAL COMO LA TRAE LA SIB. Se expone sin traducir a ningún otro
            # vocabulario: cruzarla con los dominios de la ENCFT exige comprobar antes que
            # las dos nomenclaturas hablen de lo mismo, y un mapa inventado en el medio es
            # exactamente lo que este repo no hace.
            "region_segun_la_sib": region_de.get(provincia),
            "deuda": round(acc["deuda"], 2),
            # El SUJETO en la clave: es la cuota sobre el crédito clasificado de la
            # población que la función recibe —el sistema o una entidad—, no sobre el sector.
            "peso_en_la_cartera_pct": _pct(acc["deuda"], total),
            "sectores_en_que_presta": 0,   # se completa abajo, del mismo barrido
            "entidades_que_prestan": len(acc["bancos"]),
        }
        fila.update({k: v for k, v in _medidas(acc).items()
                     if k in ("mora_pct", "mora_temprana_31_90_pct",
                              "tasa_promedio_ponderada_pct", "garantia_sobre_deuda_pct",
                              "creditos", "credito_promedio")})
        filas.append(fila)
    # El conteo de sectores por provincia, del mismo barrido.
    sectores: Dict[str, set] = {}
    for c in celdas:
        sectores.setdefault(str(c.provincia), set()).add(str(c.sector))
    for f in filas:
        f["sectores_en_que_presta"] = len(sectores.get(str(f["provincia"]), ()))
    filas.sort(key=lambda f: -float(f["deuda"] or 0))
    return filas


def sistema_por_sector(db: Session, corte: date) -> Dict[str, Any]:
    """El sistema entero abierto por sector, agregando sobre provincias y entidades."""
    celdas = _celdas(db, corte)
    por_sector = _agregar(celdas)
    if not por_sector:
        return {"corte": str(corte), "sectores": [], "sin_dato": True}

    total = sum(a["deuda"] for a in por_sector.values())
    sectores = []
    for sector, acc in por_sector.items():
        fila = {
            "sector": sector,
            "deuda": round(acc["deuda"], 2),
            # El SUJETO en la clave: esta cuota es sobre el crédito TOTAL del sistema, no
            # sobre la cartera de ninguna entidad.
            "peso_en_el_sistema_pct": _pct(acc["deuda"], total),
            "entidades_que_prestan": len(acc["bancos"]),
        }
        fila.update(_medidas(acc))
        sectores.append(fila)
    sectores.sort(key=lambda s: -float(s["deuda"] or 0))
    # UNA sola vez: computarlo dos veces —una para servir y otra para acumular— es cómo las
    # dos copias terminan discrepando, que es el defecto que borró la tasa de 38 entidades.
    provincias = _por_provincia(celdas, total)
    return {
        "corte": str(corte),
        "credito_total_del_sistema": round(total, 2),
        "sectores": sectores,
        # LA GEOGRAFÍA DEL CRÉDITO. El cubo es sector × provincia y la provincia se estaba
        # agregando hasta desaparecer: 33 provincias guardadas y ninguna servida.
        "provincias": provincias,
        # LOS ACUMULADOS, COMPUTADOS. Servir 33 provincias y 19 sectores con su peso
        # individual y ningún total parcial deja al modelo haciendo la suma: el anuario
        # escribió «ambas jurisdicciones metropolitanas concentran el 68,32 %», que era
        # 54,64 + 13,68 hecho a mano. Acertó; en comercio la misma cuenta dio 42,2 cuando el
        # dato era 42,3. Se acumula sobre la DEUDA cruda, no sobre los pesos ya redondeados.
        "concentracion_por_provincia": concentracion_top_n(
            provincias, clave_peso="deuda", clave_nombre="provincia",
            poblacion="provincias del cubo de crédito de la SIB"),
        "concentracion_por_sector": concentracion_top_n(
            sectores, clave_peso="deuda", clave_nombre="sector",
            poblacion="sectores CIIU del cubo de crédito de la SIB"),
        "que_es": ("el crédito de TODAS las entidades supervisadas abierto por sector "
                   "económico; la mora temprana de 31 a 90 días se deteriora antes que la "
                   "vencida, así que ordena por anticipación y no por daño consumado"),
        "como_se_agrega_la_tasa": ("promedio ponderado por saldo adeudado, tal como la "
                                   "define la SIB; las celdas sin tasa creíble salen del "
                                   "numerador y del denominador"),
    }


#: Por qué no hay mapa sectorial en un corte. Se DECLARA, no se omite: una sección que
#: desaparece se lee como que el producto no la trae, y la pregunta que el lector se hace
#: —«¿este banco no presta por sector, o ustedes no lo tienen?»— queda sin responder.
#:
#: Los dos motivos son distintos y solo uno es nuestro. Vive como constante y no incrustado
#: en la función porque un literal se parte por ancho de línea y deja de existir en el fuente.
MOTIVO_FUENTE_SIN_PUBLICAR = (
    "El desglose sectorial de este corte no está disponible: la Superintendencia de Bancos "
    "todavía no ha publicado el cubo de crédito del período. No es una omisión del análisis "
    "ni una característica de la entidad — es un dato que la fuente aún no emitió, y se "
    "declara en vez de sustituirse. La sección se incorpora cuando el cubo se publique."
)

MOTIVO_ENTIDAD_SIN_DESGLOSE = (
    "Esta entidad no registra cartera clasificada por sector económico en este corte, aunque "
    "el desglose del sistema sí está publicado. La comparación contra el resto del sistema "
    "necesita el libro sectorial propio, y sin él no se computa: se declara la ausencia en "
    "lugar de presentar una posición que no se midió."
)

MOTIVO_SISTEMA_SIN_PUBLICAR = (
    "El libro de crédito del sistema abierto por sector no está disponible para este corte: "
    "la Superintendencia de Bancos todavía no ha publicado el cubo de crédito del período. "
    "Se declara en vez de sustituirse por el corte anterior, que describiría otro trimestre."
)


def motivo_sin_mapa(db: Session, corte: date,
                    bank: Optional[Bank] = None) -> str:
    """Por qué este corte no tiene mapa sectorial — distinguiendo de QUIÉN es la ausencia.

    Sin celdas para el corte, la fuente no publicó el cubo. Con celdas pero ninguna de la
    entidad, el hueco es de la entidad. Confundirlos haría que un trimestre sin publicar se
    leyera como una característica del banco evaluado, que es exactamente la lectura que un
    informe de calificación no puede permitirse inducir.
    """
    hay_corte = bool(_celdas(db, corte))
    if bank is None:
        return "" if hay_corte else MOTIVO_SISTEMA_SIN_PUBLICAR
    if not hay_corte:
        return MOTIVO_FUENTE_SIN_PUBLICAR
    return MOTIVO_ENTIDAD_SIN_DESGLOSE


def posicion_de_la_entidad(db: Session, bank: Bank, corte: date) -> Optional[Dict[str, Any]]:
    """Dónde presta esta entidad, y cómo le va ahí contra el RESTO del sistema."""
    celdas = _celdas(db, corte)
    mias = [c for c in celdas if str(c.bank_id) == str(bank.id)]
    if not mias:
        logger.info("Mapa sectorial: %s no tiene desglose en %s.", bank.name, corte)
        return None

    todo = _agregar(celdas)
    mio = _agregar(mias)
    credito_del_sistema = sum(a["deuda"] for a in todo.values())
    mi_total = sum(a["deuda"] for a in mio.values())

    filas = []
    for sector, acc in mio.items():
        resto = _restar(todo[sector], acc)
        mi = _medidas(acc)
        su = _medidas(resto)
        material = acc["deuda"] >= MATERIALIDAD_DEUDA

        def _brecha(a: Optional[float], b: Optional[float]) -> Optional[float]:
            # LA RELACIÓN SE COMPUTA ACÁ. El modelo la copia; si tuviera que derivarla de
            # dos porcentajes, invertiría la dirección — ya pasó en este repo.
            return None if a is None or b is None else round(a - b, 2)

        fila = {
            "sector": sector,
            "deuda": round(acc["deuda"], 2),
            "provincias_en_que_presta": acc["celdas"],
            # DOS cuotas con DOS denominadores. Sin el sujeto en la clave, el modelo las
            # confunde y publica «concentra el 31% del sector» cuando es de su cartera.
            "peso_en_su_cartera_pct": _pct(acc["deuda"], mi_total),
            "cuota_del_sector_pct": _pct(acc["deuda"], todo[sector]["deuda"]),
            "peso_del_sector_en_el_sistema_pct": _pct(todo[sector]["deuda"],
                                                      credito_del_sistema),
            "entidades_en_el_resto_del_sector": len(resto["bancos"]),
            "mora_pct": mi["mora_pct"],
            "mora_del_resto_del_sector_pct": su["mora_pct"],
            "brecha_de_mora_pp": _brecha(mi["mora_pct"], su["mora_pct"]),
            "mora_temprana_31_90_pct": mi["mora_temprana_31_90_pct"],
            "mora_temprana_del_resto_del_sector_pct": su["mora_temprana_31_90_pct"],
            "brecha_de_mora_temprana_pp": _brecha(mi["mora_temprana_31_90_pct"],
                                                  su["mora_temprana_31_90_pct"]),
            # El precio al que la entidad coloca en ese sector contra el precio del resto.
            # Un spread positivo con mora igual es margen; con mora peor es riesgo mal
            # cobrado. Ninguna de las dos lecturas existe sin el libro de los demás.
            "tasa_promedio_ponderada_pct": mi["tasa_promedio_ponderada_pct"],
            "tasa_del_resto_del_sector_pct": su["tasa_promedio_ponderada_pct"],
            "spread_de_tasa_pp": _brecha(mi["tasa_promedio_ponderada_pct"],
                                         su["tasa_promedio_ponderada_pct"]),
            "cobertura_de_provision_sobre_vencida_pct":
                mi["cobertura_de_provision_sobre_vencida_pct"],
            "cobertura_del_resto_del_sector_pct":
                su["cobertura_de_provision_sobre_vencida_pct"],
            "garantia_sobre_deuda_pct": mi["garantia_sobre_deuda_pct"],
            "garantia_del_resto_del_sector_pct": su["garantia_sobre_deuda_pct"],
            "dolarizacion_de_la_deuda_pct": mi["dolarizacion_de_la_deuda_pct"],
            "dolarizacion_del_resto_del_sector_pct": su["dolarizacion_de_la_deuda_pct"],
            "deuda_de_persona_fisica_pct": mi["deuda_de_persona_fisica_pct"],
            "creditos": mi["creditos"],
            "credito_promedio": mi["credito_promedio"],
            "credito_promedio_del_resto_del_sector": su["credito_promedio"],
            "desembolso_del_trimestre": mi["desembolso_del_trimestre"],
            "atribucion": _atribuir(_brecha(mi["mora_pct"], su["mora_pct"]), material,
                                    hay_resto=resto["deuda"] > 0),
            "material": material,
        }
        filas.append(fila)
    filas.sort(key=lambda f: -float(f["deuda"] or 0))
    return {
        "entidad": bank.name,
        "corte": str(corte),
        "credito_clasificado": round(mi_total, 2),
        # DÓNDE presta, no solo a quién. La cuota de la entidad en cada provincia contra el
        # peso que esa provincia tiene en el crédito del país dice si su huella geográfica
        # sigue al mercado o se aparta de él — y un banco solo ve su propia huella.
        "provincias": _provincias_contra_el_pais(mias, celdas, mi_total,
                                                 credito_del_sistema),
        "resumen": _resumen(filas, mi_total),
        "sectores": filas,
        # LOS ACUMULADOS DE LA ENTIDAD, computados por la misma razón que los del sistema:
        # sin ellos el modelo suma a mano. La marca gemela del 2026-09-01 fue exactamente
        # ésta, del lado de los sectores — «consumo y construcción juntos representan el
        # 48,39 % de su cartera clasificada».
        "concentracion_por_sector": concentracion_top_n(
            filas, clave_peso="deuda", clave_nombre="sector",
            poblacion="sectores CIIU en que presta esta entidad"),
        "contra_que_se_compara": (
            "el RESTO del sistema en el mismo sector, EXCLUIDA la entidad; incluirla "
            "haría que se comparase en parte contra sí misma y encogería su brecha tanto "
            "más cuanto mayor fuese su cuota"),
        "regla_de_atribucion": (
            f"la brecha es la mora de la entidad menos la del MISMO sector en el resto del "
            f"sistema; por debajo de {BRECHA_MATERIAL_PP} punto porcentual no se atribuye a "
            f"ninguna de las dos causas, y por debajo de "
            f"RD${MATERIALIDAD_DEUDA:,.0f} de exposición la mora de una celda es ruido"),
    }


#: Cómo se agrupan las atribuciones para el resumen. El modelo abre la sección diciendo
#: cuánto del libro está en cada grupo, así que el agregado se le SIRVE computado.
_GRUPOS = {
    "con_deterioro_propio": ("idiosincratico_peor",),
    "con_mejor_desempeno_que_su_sector": ("idiosincratico_mejor",),
    "alineados_con_su_sector": ("compartido_con_el_sector",),
}


def _resumen(filas: List[Dict[str, Any]], mi_total: float) -> Dict[str, Any]:
    """Cuánto del libro cae en cada tipo de atribución.

    Por qué se sirve y no se deja que el modelo lo sume. La primera frase útil de esta
    sección es «los sectores donde el deterioro es propio son el X% de su cartera», y el
    modelo la necesita SIEMPRE. Sin servirla, la suma igual: el primer informe real de
    producción dijo «juntos representan el 48.39%» —correcto, 41,62 + 6,77— y el guard
    numérico la marcó como cifra sin respaldo, porque una suma que nadie sirvió no lo tiene.
    El informe siguiente, con el mismo contenido, se vetó por eso y no se entregó.

    La cura es la doctrina, no aflojar el detector: si sabés qué cifra va a necesitar el
    modelo, pasásela con su nombre real. Dejar el hueco es lo que lo llena mal — y acá lo
    llenaba BIEN, que es peor, porque el número correcto quedaba indefendible.

    Solo entran las celdas MATERIALES: sumar una exposición que la propia tabla marca como
    ruido daría un agregado que la tabla contradice."""
    out: Dict[str, Any] = {}
    for nombre, atribuciones in _GRUPOS.items():
        grupo = [f for f in filas if f.get("atribucion") in atribuciones]
        deuda = sum(float(f.get("deuda") or 0) for f in grupo)
        out[f"sectores_{nombre}"] = len(grupo)
        # El SUJETO en la clave: el denominador es la cartera clasificada de la ENTIDAD, no
        # el crédito del sistema ni el del sector.
        out[f"peso_en_su_cartera_de_los_sectores_{nombre}_pct"] = _pct(deuda, mi_total)
        # CERO, no None. Acá el cero está MEDIDO: se conoce el desglose completo y ningún
        # sector cae en este grupo. `None` diría «no sé», y las tres claves del grupo
        # —cuántos, cuánto pesan, cuánta deuda— tienen que contar la misma historia: un
        # conteo en 0 junto a una deuda en «sin dato» se lee como una tabla rota.
        out[f"deuda_en_los_sectores_{nombre}"] = round(deuda, 2)
    out["lectura"] = (
        "cada peso se computa sobre la cartera CLASIFICADA de la entidad; los sectores sin "
        "exposición material y aquellos en los que la entidad es el único prestador no "
        "entran en ningún grupo, porque no hay atribución que hacerles")
    return out


def _provincias_contra_el_pais(mias: List[CarteraSectorial], todas: List[CarteraSectorial],
                               mi_total: float, total_pais: float) -> List[Dict[str, Any]]:
    """Dónde presta la entidad, contra dónde presta el país.

    Las DOS cuotas viajan con su población en la clave, por el mismo motivo que en la lectura
    sectorial: `peso_en_su_cartera_pct` es sobre su libro y `peso_de_la_provincia_en_el_pais_pct`
    sobre el crédito nacional. Confundirlas publica «concentra el 40% de Santiago» cuando es
    el 40% de su propia cartera.

    La brecha entre las dos es la RELACIÓN y se computa acá: positiva significa que la
    entidad está SOBRE-representada en esa provincia respecto del mercado."""
    del_pais = {p["provincia"]: p for p in _por_provincia(todas, total_pais)}
    filas = _por_provincia(mias, mi_total)
    for f in filas:
        pais = del_pais.get(f["provincia"]) or {}
        peso_pais = pais.get("peso_en_la_cartera_pct")
        f["peso_en_su_cartera_pct"] = f.pop("peso_en_la_cartera_pct")
        f["peso_de_la_provincia_en_el_pais_pct"] = peso_pais
        f["sobre_representacion_pp"] = (
            None if f["peso_en_su_cartera_pct"] is None or peso_pais is None
            else round(f["peso_en_su_cartera_pct"] - peso_pais, 2))
        f["mora_del_resto_del_pais_en_la_provincia_pct"] = pais.get("mora_pct")
        f["brecha_de_mora_pp"] = (
            None if f.get("mora_pct") is None or pais.get("mora_pct") is None
            else round(f["mora_pct"] - pais["mora_pct"], 2))
    return filas


def _atribuir(brecha: Optional[float], material: bool, hay_resto: bool = True) -> str:
    """Idiosincrático, compartido, o no atribuible — nunca una cuarta cosa inventada.

    `sin_resto_con_que_comparar` no es un caso degenerado que haya que esconder: es el
    hallazgo. Significa que la entidad es la ÚNICA que presta a ese sector, y entonces no
    existe referencia contra la cual atribuir su mora —ni buena ni mala—. Confundirlo con
    `sin_dato` diría «falta el dato» cuando el dato está completo y lo que falta es un
    comparable; son cosas distintas y la segunda es la interesante."""
    if not hay_resto:
        return "sin_resto_con_que_comparar"
    if brecha is None:
        return "sin_dato"
    if not material:
        return "exposicion_no_material"
    if abs(brecha) < BRECHA_MATERIAL_PP:
        return "compartido_con_el_sector"
    return "idiosincratico_peor" if brecha > 0 else "idiosincratico_mejor"
