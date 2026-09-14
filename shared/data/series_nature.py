"""Naturaleza estadística de una serie — qué tipo de magnitud mide.

**La causa raíz que este módulo cierra.** El emisor SIEMPRE declara qué mide: el BCRD
escribe "MILLONES DE US$", "%", "Índice base 2018", "Saldo al inicio del período" en el
encabezado de cada planilla. Nosotros extraíamos el valor y tirábamos esa declaración. Sin
ella, cada consumidor tiene que ADIVINAR qué transformación aplica — y el motor de
momentum adivinaba una sola para todas: variación porcentual.

Eso es un error de categoría en el 37% del catálogo:

* Una TASA que va de 4.23% a 5.35% subió **1.12 puntos porcentuales**. Reportar "+26.48%"
  es aritméticamente correcto y económicamente falso: se lee como "la inflación subió 26%".
* Un STOCK que cruza el cero (posición neta de inversión) cambia de signo, y la variación
  porcentual pierde significado.
* Un stock cuyo valor previo es casi cero produce porcentajes de siete cifras.

La corrección no es poner guardas contra denominadores chicos —eso escondería el problema
sin resolverlo—: es **capturar la naturaleza en la extracción, persistirla junto al dato, y
que cada consumidor la lea en vez de suponerla**.

Regla de decisión: la UNIDAD manda (es lo que el emisor declaró); la etiqueta solo se
consulta cuando la unidad no alcanza. Ante la duda se devuelve ``UNKNOWN``, y un consumidor
honesto no computa lo que no sabe interpretar — la misma doctrina del nulo honesto.
"""
from __future__ import annotations

import re
from typing import Optional

#: Flujo o nivel absoluto (exportaciones, remesas, PIB en moneda). Admite variación %.
FLOW = "flow"
#: Saldo o posición a una fecha (reservas, deuda, PII). El cambio de NIVEL es la lectura
#: natural; la variación % solo vale si el signo es estable y la base no es despreciable.
STOCK = "stock"
#: La serie YA es una tasa/porcentaje/participación. Su variación se mide en PUNTOS
#: PORCENTUALES, nunca en porcentaje sobre porcentaje.
RATE = "rate"
#: Número índice (base 100 o base año). La variación % es la lectura correcta; los niveles
#: no se suman entre sí.
INDEX = "index"
#: No se pudo determinar. No se computa variación porcentual: se declara no computable.
UNKNOWN = "unknown"

ALL = (FLOW, STOCK, RATE, INDEX, UNKNOWN)

#: Cómo se expresa el cambio de cada naturaleza — viaja al cliente para que el número
#: llegue con su unidad y no se lea mal.
CHANGE_UNIT = {
    RATE: "puntos porcentuales",
    INDEX: "%",
    FLOW: "%",
    STOCK: "nivel",
    UNKNOWN: None,
}

# ── Códigos canónicos PROPIOS: la naturaleza se DECLARA, no se infiere ─
#
# Las series que emiten nuestros conectores tipados (no el motor de Excel) llevan códigos
# cortos en inglés que nosotros elegimos. Para ellas adivinar sería absurdo: sabemos
# exactamente qué miden. Declararlas también cubre el hueco que la inferencia por patrón
# no puede cubrir — los patrones están en español porque leen planillas del BCRD, y estos
# códigos son ingleses (`public_debt_gdp` es un % del PIB y quedaba en `unknown`).
DECLARED: dict = {
    "gdp_growth": RATE,             # crecimiento en %
    "inflation_yoy": RATE,          # inflación interanual en %
    "public_debt_gdp": RATE,        # deuda como % del PIB
    "unemployment": RATE,
    "fiscal_balance_gdp": RATE,
    "remittances": FLOW,            # flujo en US$
    "exports": FLOW,
    "imports": FLOW,
    "fdi": FLOW,                    # inversión extranjera directa: flujo
    "capital_flows": FLOW,
    "reserves": STOCK,              # saldo de reservas
    "external_debt": STOCK,
    "fx_rate": FLOW,                # nivel del tipo de cambio
    # ── Seguros · SISALRIL (Fase 3 del plan de entregables mensuales) ──
    # Se declaran por código COMPLETO, nunca por la hoja: «total» o «patrimonio» sueltos
    # atraparían series de otros ejes que no miden esto.
    #
    # La afiliación SFS son PERSONAS CUBIERTAS a una fecha: un saldo, no lo que entró en el
    # mes. Su base es el último nivel; compararla contra el mismo mes del año anterior como a un
    # flujo mediría estación donde no la hay. Sin declarar, `infer_nature("personas")` salía
    # `unknown` y la sección del delta no la computaba.
    "sfs.afiliacion.total": STOCK,
    "sfs.afiliacion.contributivo": STOCK,
    "sfs.afiliacion.subsidiado": STOCK,
    # Agregados de SISTEMA de las ARS (suma de las 18 del roster, solo si reportan todas):
    # cuentas de balance del plan 0 del BDFINAC, saldos al cierre del mes.
    "ars.sistema.patrimonio": STOCK,
    "ars.sistema.activo_total": STOCK,
    "ars.sistema.margen_inversiones": STOCK,
    "ars.sistema.margen_requerido": STOCK,
    # Los ACUMULADOS AL MES se declaran `unknown`, explícitamente. En el fixture real CRECEN mes
    # a mes dentro del año (ingreso de una ARS: 267,9 M → 409,1 M → 553,3 M de febrero a abril).
    # Tratarlos como `flow` haría que la ventana móvil de doce meses SUME acumulados: una cifra
    # falsa con cara de medición.
    #
    # ⚠️ No alcanza con dejarlos fuera de esta tabla: la unidad «RD$» decide antes que nada y
    # `infer_nature` los devuelve `flow`. Se comprobó así, y por eso la declaración existe.
    # ── Energía · OC-SENI, IMTE (Fase 5) ──
    # La energía inyectada y retirada en el MES es un flujo: su base es el mismo mes del año
    # anterior. «GWh» no dice nada a la inferencia por unidad, por eso se declara.
    "oc_seni.imte.inyecciones_gwh": FLOW,
    "oc_seni.imte.retiros_totales_gwh": FLOW,
    "oc_seni.imte.retiros_distribuidoras_gwh": FLOW,
    # Las pérdidas de transmisión son una PROPORCIÓN de lo inyectado: se mueven en puntos.
    "oc_seni.imte.perdidas_transmision_pct": RATE,
    "ars.ingreso_salud": UNKNOWN,
    "ars.gasto_salud": UNKNOWN,
    "ars.beneficio_neto": UNKNOWN,
}


# ── Señales en la UNIDAD declarada por el emisor (prioridad 1) ────────
_UNIT_RATE = re.compile(
    r"(^|[^a-z])(%|por\s*ciento|porcentaje|porcentual|p\.?p\.?|puntos?\s+porcentuales)",
    re.IGNORECASE)
_UNIT_INDEX = re.compile(r"[íi]ndice|index|base\s*(19|20)\d{2}", re.IGNORECASE)
_UNIT_MONEY = re.compile(
    r"(mm\s*us\$|millones|miles|us\$|rd\$|d[óo]lares|pesos|euros)", re.IGNORECASE)

# ── Señales en la ETIQUETA (prioridad 2, solo si la unidad no alcanza) ─
_LABEL_RATE = re.compile(
    r"(tasa|variaci[óo]n\s+porcentual|participaci[óo]n|ponderaci[óo]n|cuota|"
    r"proporci[óo]n|ratio|inflaci[óo]n|desocupaci[óo]n|ocupaci[óo]n|"
    r"rate|share|ratio|percent|unemployment|inflation)", re.IGNORECASE)
_LABEL_INDEX = re.compile(r"[íi]ndice|imae|ipc(?!\w)", re.IGNORECASE)
_LABEL_STOCK = re.compile(
    r"(saldo|posici[óo]n|reservas?|activos?|pasivos?|deuda|stock|"
    r"existencias|acervo|circulaci[óo]n|"
    r"stock|balance|reserves?|assets?|liabilities|debt|position)", re.IGNORECASE)


def infer_nature(unit: Optional[str] = None, label: Optional[str] = None,
                 code: Optional[str] = None) -> str:
    """Naturaleza estadística de una serie, de lo que el EMISOR declaró.

    Orden de decisión —de la evidencia más fuerte a la más débil—:

    1. **La unidad.** Es lo que el emisor escribió en el encabezado de su planilla; si dice
       "%" la serie es una tasa, sin discusión posible.
    2. **La etiqueta**, solo cuando la unidad falta o es ambigua. "Tasa de desocupación" es
       una tasa aunque nadie haya puesto la unidad.
    3. **``UNKNOWN``.** No se adivina: un consumidor que no sabe qué transformación aplicar
       debe declararlo, no elegir una al azar.

    >>> infer_nature("%", "Inflación interanual")
    'rate'
    >>> infer_nature("MM US$", "Exportaciones")
    'flow'
    >>> infer_nature(None, "Reservas internacionales netas")
    'stock'
    >>> infer_nature(None, None)
    'unknown'
    """
    u = (unit or "").strip()
    lab = " ".join(x for x in (label or "", code or "") if x)

    # 0) Código propio declarado: no se adivina lo que nosotros mismos definimos.
    if code:
        leaf = str(code).split(".")[-1].strip().lower()
        if leaf in DECLARED:
            return DECLARED[leaf]
        if str(code).strip().lower() in DECLARED:
            return DECLARED[str(code).strip().lower()]

    # 1) La unidad manda.
    if u:
        if _UNIT_RATE.search(u):
            return RATE
        if _UNIT_INDEX.search(u):
            return INDEX
        if _UNIT_MONEY.search(u):
            # Moneda: distinguir saldo de flujo. La señal de "saldo" puede venir en la
            # PROPIA unidad ("Saldos en millones de RD$" — así lo titula el BCRD sus
            # agregados monetarios) o en la etiqueta ("Posición de inversión"). Sin señal,
            # flujo. Se mira la unidad y la etiqueta juntas.
            return STOCK if _LABEL_STOCK.search(f"{u} {lab}") else FLOW

    # 2) La etiqueta, si la unidad no alcanzó.
    if lab:
        if _LABEL_RATE.search(lab):
            return RATE
        if _LABEL_INDEX.search(lab):
            return INDEX
        if _LABEL_STOCK.search(lab):
            return STOCK

    # 3) Sin evidencia: no se inventa.
    return UNKNOWN


def percent_change_is_valid(nature: str) -> bool:
    """¿Tiene sentido una variación PORCENTUAL para esta naturaleza?

    Para una tasa NO: su variación se mide en puntos. Para un stock tampoco de forma
    general —puede cruzar el cero— y se decide observación a observación. Para lo
    desconocido, nunca."""
    return nature in (FLOW, INDEX)
