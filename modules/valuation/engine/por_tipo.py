"""Los parámetros del modelo que dependen del TIPO de entidad, con qué los sostiene.

La Superintendencia supervisa cuatro clases de entidad de intermediación y el modelo las
trataba a las cuatro igual: la misma beta de bancos cotizados latinoamericanos y la misma
retención del 60 %. Los datos dicen que no son lo mismo.

**Lo medido** (SIMBAD, cierres 2019-2025, 145 entidad-año):

    dispersión de ROE (p75 − p25, en pp), año por año
    ────────────────────────────────────────────────────────────────────
    año    banca múltiple   ahorro y crédito   asociaciones   corp. créd.
    2020        15,3               8,4              2,0           8,6
    2021        23,6               7,3              2,0           3,9
    2022        12,7              13,8              4,0           7,6
    2023        21,2               6,2              3,5           6,5
    2024        17,6              11,8              3,4           0,7
    2025        19,3               6,3              2,4           5,2

**Qué sostiene y qué no.** Las asociaciones son las menos dispersas los SEIS de seis años, y
la banca múltiple la más dispersa CINCO de seis. Eso es un orden estable en los extremos. Lo
que la evidencia NO sostiene es un orden fino de cuatro: los dos del medio se cruzan, y las
corporaciones de crédito son **tres entidades** — su dispersión es ruido, no medición.

Por eso la beta se abre en **TRES** grupos y no en cuatro, y las corporaciones comparten el
de ahorro y crédito **por falta de muestra**, no porque se haya medido que se parecen.

**Y una advertencia sobre qué mide esa tabla.** Dispersión de ROE es riesgo TOTAL; beta es
riesgo SISTEMÁTICO, que es otra cosa. La tabla sostiene el ORDEN entre tipos; el TAMAÑO del
salto entre bandas es rúbrica, y se declara como tal. Sin entidades dominicanas cotizadas no
hay forma de medirlo, y fingir que la hay sería peor que decirlo.
"""
from __future__ import annotations

from typing import Dict, Tuple

#: Beta de equity por tipo. La de banca múltiple es la original y no se toca: es la clase que
#: se parece a los bancos cotizados latinoamericanos de donde salió. Las otras bajan desde
#: ahí, en el orden que los datos sostienen.
BETA_POR_TIPO: Dict[str, Tuple[float, float]] = {
    "banca_multiple": (0.85, 1.15),
    "banco_ahorro_credito": (0.75, 1.05),
    "corporacion_credito": (0.75, 1.05),
    "aap": (0.60, 0.90),
}

#: Por qué cada grupo tiene la banda que tiene. Viaja al informe: un parámetro que cambia el
#: valor y no dice de dónde sale es un número inventado con buena presentación.
BETA_EVIDENCIA_POR_TIPO: Dict[str, str] = {
    "banca_multiple": (
        "Banda original, sin cambio: es la clase que se parece a los bancos cotizados "
        "latinoamericanos de los que sale la beta. Y es la más dispersa del sistema —entre "
        "12,7 y 23,6 pp de rango intercuartil de ROE según el año, la más alta en cinco de "
        "seis años—, así que no hay motivo para bajarla."),
    "banco_ahorro_credito": (
        "Un escalón por debajo de la banca múltiple. Su dispersión de ROE es "
        "consistentemente menor —entre 6,2 y 13,8 pp— aunque no de forma tan limpia como en "
        "los extremos: algún año cruza con las corporaciones de crédito."),
    "corporacion_credito": (
        "COMPARTE la banda de los bancos de ahorro y crédito, y no porque se haya medido que "
        "se parecen: son TRES entidades, y la dispersión de tres observaciones es ruido. Se "
        "les da la banda del grupo más cercano por tamaño y negocio, y se declara que es por "
        "falta de muestra."),
    "aap": (
        "La banda más baja. Es lo mejor sostenido de toda la tabla: las asociaciones son las "
        "MENOS dispersas los seis de seis años medidos, entre 2,0 y 4,0 pp de rango "
        "intercuartil, contra los 12,7-23,6 de la banca múltiple. Cartera hipotecaria, "
        "resultados estables."),
}

#: Retención `b` MEDIDA por tipo: mediana de ΔPatrimonio / Utilidad sobre 145 entidad-año
#: (2019-2025), acotada a [0,1]. Reemplaza una rúbrica del 60 % igual para las cuatro.
RETENCION_POR_TIPO: Dict[str, float] = {
    "banca_multiple": 0.75,
    "banco_ahorro_credito": 0.74,
    "corporacion_credito": 0.76,
    "aap": 0.99,
}

RETENCION_EVIDENCIA_POR_TIPO: Dict[str, str] = {
    "banca_multiple": "Mediana de ΔPatrimonio/Utilidad sobre 54 entidad-año (2019-2025).",
    "banco_ahorro_credito": "Mediana sobre 51 entidad-año (2019-2025).",
    "corporacion_credito": "Mediana sobre 15 entidad-año (2019-2025). Muestra chica.",
    "aap": (
        "Mediana sobre 25 entidad-año (2019-2025), y el 0,99 NO es un artefacto: las "
        "asociaciones son MUTUALES y no tienen accionistas a quienes pagar dividendos, así "
        "que retienen todo lo que ganan. Es la diferencia por tipo mejor sostenida de todas, "
        "y el modelo la trataba con el mismo 60 % que a un banco."),
}

#: Cuando el tipo no se conoce. Se usa el de banca múltiple —la clase más grande y la de la
#: beta original— y se DECLARA, porque un defecto silencioso acá cambia el valor.
TIPO_POR_DEFECTO = "banca_multiple"


def beta_de(tipo: str | None) -> Tuple[float, float]:
    return BETA_POR_TIPO.get(tipo or "", BETA_POR_TIPO[TIPO_POR_DEFECTO])


def retencion_de(tipo: str | None) -> float:
    return RETENCION_POR_TIPO.get(tipo or "", RETENCION_POR_TIPO[TIPO_POR_DEFECTO])


def evidencia_de(tipo: str | None) -> str:
    """Las dos evidencias juntas, más el aviso cuando el tipo no se reconoció."""
    t = tipo if tipo in BETA_POR_TIPO else None
    if t is None:
        return (f"TIPO DE ENTIDAD NO RECONOCIDO ({tipo!r}): se usan los parámetros de "
                f"{TIPO_POR_DEFECTO}, que son los más exigentes en beta. Se declara porque "
                "cambia el valor.\n\n"
                + BETA_EVIDENCIA_POR_TIPO[TIPO_POR_DEFECTO])
    return f"{BETA_EVIDENCIA_POR_TIPO[t]}\n\nRetención: {RETENCION_EVIDENCIA_POR_TIPO[t]}"
