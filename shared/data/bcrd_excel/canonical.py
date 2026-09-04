"""Canonical BCRD series registry — the curated, base-homogeneous selection.

The BCRD portal has ~708 Excel files, but they are the same concepts repeated
across bases (IPC 1999/2010/2019-2020; PIB 2007/2018), per-year slices and
disaggregations. This registry is the ~25 *canonical* series an analyst should
cite: one definitive source per concept, with the base, the homogenization
strategy, the economist's rationale, the data robustness, and the live-API series
it ties to. It is the single source of truth for both ingestion (we ingest only
these) and the in-app documentation surface.

Robustness:
  - "green"  — extracts cleanly today and is validatable.
  - "yellow" — extracts but needs review / splicing / consolidation.
  - "red"    — the engine does not extract it yet (pending extraction work).

See ``docs/SERIES_CANONICAS_BCRD.md`` for the full rationale.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

Robustness = str  # "green" | "yellow" | "red"


@dataclass(frozen=True)
class CanonicalSeries:
    key: str                       # stable slug
    concept: str                   # human concept name
    sector: str                    # BCRD statistics sector
    source_file: str               # canonical catalog filename
    base: str                      # base year / unit
    frequency: str                 # mensual | trimestral | anual | diaria
    homogenization: str            # how it's made base-homogeneous
    rationale: str                 # economist's reason for this base/source
    robustness: Robustness
    api_series: Optional[str] = None      # tied live-API MacroSeries code
    api_transform: Optional[str] = None   # "identity" | "yoy" — how to compare vs API
    excel_series_suffix: Optional[str] = None  # extracted series_code endswith (for ingest/crosscheck)


# Notas metodológicas por PREFIJO de código de serie. Viajan al cliente por la Data API
# (``/catalog`` y ``/series``), que es donde hacen falta: un consumidor que ve dos series de
# balanza de pagos necesita saber, sin preguntar, que responden a manuales distintos y que
# encadenarlas fabrica un salto. La medición del quiebre (año 2010, publicado por ambas):
# remesas 2,998 (MBP5) vs 3,683 (MBP6) = +23%; cuenta corriente −4,330 vs −4,024 = +7%.
SERIES_NOTES = {
    "bcrd.xls.bpagos_6.": (
        "Balanza de pagos bajo el MBP6 del FMI (sexta edición del manual), serie OFICIAL "
        "VIGENTE del BCRD desde 2010. NO encadenar con la serie MBP5 (bcrd.xls.bpagos.*): "
        "son metodologías distintas y el empalme fabrica un salto que no ocurrió."
    ),
    "bcrd.xls.piianual_6.": (
        "Posición de inversión internacional bajo el MBP6 del FMI (sexta edición del "
        "manual), serie OFICIAL VIGENTE del BCRD desde 2009. NO encadenar con la serie "
        "MBP5 (bcrd.xls.piianual.*): son metodologías distintas."
    ),
    "bcrd.xls.piianual.": (
        "Posición de inversión internacional bajo el MBP5 (quinta edición del manual), "
        "2005-2013 — serie HISTÓRICA y DESCONTINUADA. Úsese solo para el período previo "
        "a 2009. NO es comparable ni encadenable con la serie MBP6 "
        "(bcrd.xls.piianual_6.*)."
    ),
    "bcrd.xls.pib_origen_2018.pib_trim_acum.": (
        "PIB por actividad ACUMULADO del año: el valor de un trimestre es el corrido desde "
        "enero (el de Q2 es enero-junio, no abril-junio). NO se compara ni se suma con la "
        "serie de flujo trimestral (bcrd.xls.pib_origen_2018.pib_trim.*), que mide el "
        "trimestre solo; el acumulado del cuarto trimestre ES el año completo."
    ),
    "bcrd.xls.pib_origen_2018.pibk_trim_acum.": (
        "Índice de volumen encadenado por actividad, ACUMULADO del año: el valor de un "
        "trimestre corresponde al corrido desde enero. NO se compara ni se encadena con la "
        "serie de flujo trimestral (bcrd.xls.pib_origen_2018.pibk_trim.*). Ojo: el acumulado "
        "de un índice es un promedio ponderado, no una suma — no se reconstruye sumando los "
        "trimestres."
    ),
    "bcrd.xls.bpagos.": (
        "Balanza de pagos bajo el MBP5 (quinta edición del manual) — serie HISTÓRICA y "
        "DESCONTINUADA: el BCRD dejó de actualizar este archivo en 2019. Úsese solo para el "
        "período previo a 2010. NO es comparable ni encadenable con la serie MBP6 "
        "(bcrd.xls.bpagos_6.*): en 2010, el único año que ambas publican, las remesas "
        "difieren 23%."
    ),
}


# Series CURADAS por código exacto: elegidas y nombradas por un analista, con etiqueta
# defendible ante un cliente. Todo lo demás que sale del motor de Excel es extracción
# masiva —dato real, pero con el nombre que la planilla dejó—, y se declara como
# no-curado para que un informe no lo cite por la ruta de la hoja de cálculo.
CURATED_LABELS = {
    "bcrd.xls.reservas_internacionales.reservas_netas":
        "Reservas internacionales netas (BCRD)",
    "bcrd.xls.reservas_internacionales.reservas_brutas":
        "Reservas internacionales brutas (BCRD)",
    "bcrd.xls.reservas_internacionales.activos_brutos":
        "Activos externos brutos (BCRD)",
    "bcrd.xls.remesas_6.valor": "Remesas familiares recibidas (BCRD)",
    "fiscal_eo.ingresos": "Ingresos del Gobierno Central (Hacienda)",
    "fiscal_eo.gastos": "Gastos del Gobierno Central (Hacienda)",
    "fiscal_eo.balance_global": "Balance fiscal global del Gobierno Central (Hacienda)",
    "fiscal_eo.resultado_operativo": "Resultado operativo del Gobierno Central (Hacienda)",
    "public_debt_gdp": "Deuda pública (% del PIB)",
    "gdp_growth": "Crecimiento del PIB real",
    "inflation_yoy": "Inflación interanual",
    "remittances": "Remesas",
    "bcrd.xls.bpagos_6.1_cuenta_corriente":
        "Cuenta corriente de la balanza de pagos (MBP6)",
}


def curated_label(series_code: str) -> str:
    """Etiqueta curada de una serie, o cadena vacía si no la tiene."""
    return CURATED_LABELS.get(str(series_code), "")


def is_curated(series_code: str) -> bool:
    """¿La serie fue elegida y nombrada por un analista?

    Criterio: está en el mapa curado, o proviene de un conector TIPADO (cualquier código
    que no salga del motor genérico de Excel). El motor de Excel infiere nombres leyendo
    celdas: produce dato real con nombres que no son defendibles en un informe."""
    code = str(series_code or "")
    if code in CURATED_LABELS:
        return True
    return not code.startswith("bcrd.xls.")


def note_for(series_code: str) -> str:
    """Nota metodológica de una serie, por prefijo. Cadena vacía si no tiene."""
    for prefix, note in SERIES_NOTES.items():
        if str(series_code).startswith(prefix):
            return note
    return ""


# El IPC por QUINTIL DE INGRESO. Cinco series, una por quintil, generadas en vez de
# copiadas: comparten todo salvo el número, y cinco copias del mismo texto se desincronizan
# en cuanto alguien edite una.
#
# Por qué estas series y no el IPC general. La inflación del titular es un promedio de la
# economía; la que aprieta a un hogar endeudado es la de SU canasta. Medido sobre la base
# vigente: desde octubre de 2020 el quintil 1 acumuló 43,4% y el quintil 5 36,3% — siete
# puntos de brecha que el índice general no muestra. La cartera de consumo del sistema vive
# en los quintiles bajos, así que ésta es la variable de capacidad de pago que faltaba.
#
# Se ingiere el ÍNDICE y la variación se deriva como YoY, igual que el IPC general. Las
# columnas de tasa de la planilla —variación MENSUAL de cada quintil— ya no se pierden: la
# inferencia las califica con el encabezado de su grupo (`quintil_2 · tasa de inflación`) en
# vez de desempatarlas por coordenada de columna. Antes salían como `..._c5` y se creyó que
# eran innombrables; se verificó contra el dato que cada una coincide con error 0,00000 pp
# con la variación mensual del índice de su quintil.
_IPC_QUINTILES = [
    CanonicalSeries(
        key=f"ipc_quintil_{q}", concept=f"IPC del quintil {q} de ingreso", sector="precios",
        source_file="ipc_quintiles_base_2019-2020.xls", base="2019-2020", frequency="mensual",
        homogenization="base vigente para el nivel; variación interanual (YoY) para comparar",
        rationale=("La inflación que enfrenta cada quintil difiere de la general: la canasta "
                   "de un hogar de ingreso bajo pesa distinto. Es la medida de capacidad de "
                   "pago que explica el deterioro de la cartera de consumo, que se concentra "
                   "en los quintiles bajos."),
        robustness="green", api_series=None, api_transform="yoy",
        excel_series_suffix=f"quintil_{q}",
    )
    for q in (1, 2, 3, 4, 5)
]

# El COSTO de la canasta familiar en RD$, por quintil de ingreso. Es la otra mitad de la
# capacidad de pago y la que se lee sin traducción: el IPC dice cuánto SUBIÓ la canasta de un
# hogar; esto dice cuánto CUESTA. Contra el salario mínimo da una frase que no necesita
# índices —«el piso de ingreso cubre el 94% de la canasta del quintil más pobre»— y el propio
# documento metodológico del BCRD señala esa comparación como la referencia de las
# discusiones sobre el salario mínimo del sector privado no sectorizado.
#
# Importa en crédito porque el consumo se origina contra ingreso: un hogar cuyo piso legal no
# cubre su canasta financia el faltante, y ese faltante es cartera. Mensual desde 2018.
_COSTO_CANASTA = [
    CanonicalSeries(
        key=f"costo_canasta_quintil_{q}",
        concept=f"Costo de la canasta familiar del quintil {q} de ingreso (RD$)",
        sector="precios",
        source_file="Costo_Canasta_quintiles_base_2019-2020.xlsx", base="2019-2020",
        frequency="mensual",
        homogenization="nivel en RD$ corrientes; la variación se deriva como YoY",
        rationale=("Cuánto CUESTA en pesos la canasta de cada quintil, no cuánto subió. "
                   "Contra el salario mínimo mide directamente si el piso de ingreso alcanza, "
                   "y el faltante de un hogar que no llega es exactamente lo que financia el "
                   "crédito de consumo."),
        robustness="green", api_series=None, api_transform="yoy",
        excel_series_suffix=f"quintil_{q}",
    )
    for q in (1, 2, 3, 4, 5)
]

# El IPC por GRUPO de la canasta (las doce divisiones COICOP) y por REGIÓN. Mismo motivo
# que los quintiles: el promedio de la economía no es lo que aprieta a un hogar. La mora de
# consumo no la mueve la inflación general sino la de lo que el hogar NO puede dejar de
# comprar —alimentos, transporte, vivienda—, y la regional cruza con la provincia que el
# libro de crédito ya trae.
#
# Se ingiere el ÍNDICE; la variación se deriva como YoY. Las columnas «Var. %» de la
# planilla se descartan por la misma razón que en quintiles.
_IPC_GRUPOS = [
    CanonicalSeries(
        key=f"ipc_grupo_{k}", concept=f"IPC — {etiqueta}", sector="precios",
        source_file="ipc_grupos_base_2019-2020.xls", base="2019-2020", frequency="mensual",
        homogenization="base vigente para el nivel; variación interanual (YoY) para comparar",
        rationale=("La inflación de la canasta que el hogar no puede posponer explica el "
                   "deterioro de la cartera de consumo mejor que el índice general."),
        robustness="green", api_series=None, api_transform="yoy",
        excel_series_suffix=f"{k}_indice",
    )
    for k, etiqueta in (
        ("alimentos_y_bebidas_no_alcoholicas", "Alimentos y bebidas no alcohólicas"),
        ("bebidas_alcoholicas_y_tabaco", "Bebidas alcohólicas y tabaco"),
        ("prendas_de_vestir_y_calzado", "Prendas de vestir y calzado"),
        ("vivienda", "Vivienda"), ("muebles", "Muebles"), ("salud", "Salud"),
        ("transporte", "Transporte"), ("comunicaciones", "Comunicaciones"),
        ("recreacion_y_cultura", "Recreación y cultura"), ("educacion", "Educación"),
        ("restaurantes_y_hoteles", "Restaurantes y hoteles"),
        ("bienes_y_servicios_diversos", "Bienes y servicios diversos"),
    )
]

_IPC_REGIONES = [
    CanonicalSeries(
        key=f"ipc_region_{k}", concept=f"IPC de la región {etiqueta}", sector="precios",
        source_file="ipc_regiones_base_2019-2020.xls", base="2019-2020", frequency="mensual",
        homogenization="base vigente para el nivel; variación interanual (YoY) para comparar",
        rationale=("El crédito trae provincia desde el cubo de la SIB; la inflación regional "
                   "permite leer el deterioro de una cartera contra el costo de vida de "
                   "DONDE se prestó, y no contra un promedio nacional que no le aplica."),
        robustness="green", api_series=None, api_transform="yoy",
        excel_series_suffix=f"region_{k}",
    )
    for k, etiqueta in (("ozama", "Ozama"), ("norte", "Norte"), ("este", "Este"),
                        ("sur", "Sur"))
]

# Order roughly follows the BCRD statistics sectors shown in the portal.
REGISTRY: List[CanonicalSeries] = [
    # ── Precios ──────────────────────────────────────────────────
    CanonicalSeries(
        key="ipc_general", concept="IPC general", sector="precios",
        source_file="ipc_base_2019-2020.xls", base="2019-2020", frequency="mensual",
        homogenization="base vigente para el nivel; variación interanual (YoY) para serie larga",
        rationale="Base oficial vigente desde 2020; el API ya la expone profunda. La inflación "
                  "se mide en YoY, que es invariante a la base.",
        robustness="green", api_series="bcrd.ipc.indice", api_transform="yoy",
        excel_series_suffix="indice",
    ),
    CanonicalSeries(
        key="ipc_empalme", concept="IPC — empalme histórico", sector="precios",
        source_file="ipc_base_2019-2020_serie_referencial.xlsx", base="2019-2020 (empalmada)",
        frequency="mensual",
        homogenization="serie referencial ya encadenada por el BCRD (no encadenamos nosotros)",
        rationale="El propio BCRD publica el empalme oficial de bases; preferirlo a un "
                  "encadenamiento propio reduce el riesgo metodológico.",
        robustness="yellow", api_series="bcrd.ipc.indice", api_transform="yoy",
        excel_series_suffix="indice",
    ),
    CanonicalSeries(
        key="inflacion_interanual", concept="Inflación interanual", sector="precios",
        source_file="ipc_base_2019-2020.xls", base="n/a (tasa)", frequency="mensual",
        homogenization="YoY del IPC — invariante a la base",
        rationale="Ancla de validación: coincide con el API en 312/312 meses. Es el dato más "
                  "robusto cuando hay empalmes de base.",
        robustness="green", api_series="bcrd.inflacion.inflacion.interanual", api_transform="identity",
    ),
    *_IPC_QUINTILES,
    *_COSTO_CANASTA,
    *_IPC_GRUPOS,
    *_IPC_REGIONES,
    CanonicalSeries(
        key="ipc_subyacente", concept="IPC subyacente (núcleo)", sector="precios",
        source_file="ipc_subyacente_base_2019-2020.xlsx", base="2019-2020", frequency="mensual",
        homogenization="base vigente; YoY para comparabilidad",
        rationale="Núcleo inflacionario: excluye los componentes volátiles; guía de política.",
        robustness="yellow",
    ),
    # ── Sector Real ──────────────────────────────────────────────
    CanonicalSeries(
        key="imae", concept="IMAE (actividad económica)", sector="sector_real",
        # El BCRD migró el IMAE al archivo base 2018 (imae_2018.xlsx); el viejo imae.xlsx
        # (base 2007) quedó congelado en oct-2024. Repuntamos al vigente (cubre 2007→hoy,
        # separadores 'Promedio {año}'). El YoY interanual es invariante a la base.
        source_file="imae_2018.xlsx", base="2018=100", frequency="mensual",
        homogenization="índice + YoY (interanual base-invariante)",
        rationale="Único indicador de actividad de alta frecuencia; mensual desde 2007.",
        robustness="green", api_series="bcrd.sector_real.imaes", api_transform="identity",
        # El sufijo decía `serie_original_variacion_porcentual_interanual` y NINGUNA de las
        # series del archivo termina así: era la única entrada con puente que no resolvía a
        # nada. Cuál es la correcta se COMPUTÓ contra el dato —cuatro candidatas llevan
        # "interanual" en el nombre y solo ésta coincide, con error 0,00000 pp, con la
        # variación interanual del índice original—. Elegir por parecido de rótulo es cómo se
        # llegó al sufijo roto. Lo vigila `tests/test_puentes_canonicos.py`.
        excel_series_suffix="variacion_porcentual_interanual",
    ),
    CanonicalSeries(
        key="imae_indice", concept="IMAE — índice de actividad (nivel)", sector="sector_real",
        source_file="imae_2018.xlsx", base="2018=100", frequency="mensual",
        homogenization="nivel del índice en la base vigente; la variación se deriva como YoY",
        # Son DOS series, no una corregida. La YoY no permite reconstruir el nivel, y el
        # nowcast necesita el NIVEL: la bridge equation agrega el índice mensual a trimestre
        # y lo regresa contra el PIB. Con la serie de variación ese agregado no se puede
        # construir. Además `tpm_modeling/dataset.py` ya consume este `series_code` para el
        # output gap, así que el índice hacía falta y el registro no lo declaraba —el dato
        # entraba igual porque la ingesta es por ARCHIVO, pero sin declararlo ninguna
        # verificación podía vigilarlo.
        rationale="Nivel de actividad de alta frecuencia: es el insumo del nowcast trimestral "
                  "del PIB y del output gap, que necesitan el índice y no su variación.",
        robustness="green", api_series="bcrd.sector_real.imaes", api_transform="identity",
        excel_series_suffix="serie_original_indice",
    ),
    CanonicalSeries(
        key="pib_real", concept="PIB real (crecimiento)", sector="sector_real",
        source_file="pib_2018.xlsx", base="2018", frequency="trimestral",
        homogenization="base 2018 vigente; series '*_retro' (2007 empalmado) para historia; "
                       "el crecimiento (YoY del volumen) es invariante a la base",
        rationale="Base oficial vigente; el crecimiento real es la medida citable y base-invariante.",
        robustness="green",  # period_rows trimestral (trimestres + marcador de año)
        excel_series_suffix="serie_original_indice",
    ),
    CanonicalSeries(
        key="pib_sectores_origen", concept="PIB por sector de origen (desagregación sectorial)",
        sector="sector_real",
        # OJO — el archivo NO es `PIB_sectores_origen.xls`, que es el que uno esperaría por el
        # nombre y el que el spec de persistencia señalaba. Ése está CONGELADO: su
        # `last-modified` es del 2019-02-23 y sus dos hojas son «Trim Acum 91-14», o sea que
        # termina en 2014 y en la base vieja. Es la misma trampa del IMAE: el BCRD migró a un
        # archivo base 2018 y el anterior quedó quieto. El vigente se actualizó el 2026-06-29.
        source_file="pib_origen_2018.xlsx", base="2018", frequency="trimestral",
        homogenization="índice de volumen encadenado referenciado a 2018, por actividad; "
                       "el crecimiento se deriva como YoY, que es invariante a la base",
        rationale="La desagregación por actividad del PIB: es lo que permite decir qué sector "
                  "empuja o frena el crecimiento, y el insumo de la proyección sectorial.",
        # AMARILLO, y el motivo es concreto: de las cuatro hojas del libro, las dos
        # trimestrales (`PIB$_Trim`, `PIBK_Trim`) extraen limpias —162 series, todas con
        # períodos trimestrales 2018-Q1→2025-Q4, cero duplicados con valores en conflicto—
        # pero las dos ACUMULADAS mezclan períodos anuales y trimestrales dentro de la misma
        # serie y producen 1.660 duplicados con valores distintos, que el upsert resolvería
        # por orden de lectura. Como la ingesta es por ARCHIVO y no por hoja, el libro entero
        # queda fuera de `PERSISTIBLES_VERIFICADOS` hasta que las acumuladas se parseen bien.
        robustness="yellow",
    ),
    CanonicalSeries(
        key="pib_nominal_gasto", concept="PIB nominal por gasto", sector="sector_real",
        source_file="pib_gasto.xls", base="corriente", frequency="anual",
        homogenization="nivel corriente directo",
        rationale="Demanda agregada (consumo, inversión, exportaciones netas) en RD$ corrientes.",
        robustness="yellow",
    ),
    CanonicalSeries(
        key="pib_deflactor", concept="Deflactor del PIB", sector="sector_real",
        source_file="pib_deflactor_2018.xlsx", base="2018", frequency="trimestral",
        homogenization="YoY como inflación implícita",
        rationale="Medida amplia de precios de toda la economía (no solo consumo).",
        robustness="green",  # period_rows trimestral
        excel_series_suffix="deflactor_del_pib",
    ),
    # ── Sector Externo ───────────────────────────────────────────
    CanonicalSeries(
        key="reservas_brutas", concept="Reservas internacionales brutas", sector="sector_externo",
        source_file="reservas_internacionales.xlsx", base="US$ MM", frequency="mensual",
        homogenization="nivel directo; quiebre metodológico 2003 como series separadas",
        rationale="Colchón externo. El API solo da el último mes (snapshot) → el Excel aporta la historia.",
        robustness="green", api_series="bcrd.sector_externo.reservas_internacionales.brutas",
        api_transform="identity", excel_series_suffix=".reservas_brutas",
    ),
    CanonicalSeries(
        key="reservas_netas", concept="Reservas internacionales netas", sector="sector_externo",
        source_file="reservas_internacionales.xlsx", base="US$ MM", frequency="mensual",
        homogenization="nivel directo",
        rationale="Reservas netas de pasivos de corto plazo; complemento de las brutas.",
        robustness="green", api_series="bcrd.sector_externo.reservas_internacionales.netas",
        api_transform="identity", excel_series_suffix=".reservas_netas",
    ),
    # ── Balanza de pagos: DOS series, DOS manuales. NO se encadenan ──
    # El BCRD publica la balanza en dos archivos que responden a ediciones distintas del
    # Manual de Balanza de Pagos del FMI. Concatenarlas produciría un salto metodológico
    # con apariencia de evento económico: en el año que ambas publican (2010), las remesas
    # difieren 23% (2,998 MBP5 vs 3,683 MBP6) y la cuenta corriente 7%. Por eso viven como
    # series separadas, cada una declarando su manual y su vigencia.
    CanonicalSeries(
        key="balanza_pagos_mbp6", concept="Balanza de pagos (MBP6, vigente)",
        sector="sector_externo",
        source_file="bpagos_6.xls", base="US$ MM", frequency="anual",
        homogenization="nivel directo; serie oficial vigente del BCRD",
        rationale="Cuenta corriente y financiera bajo la SEXTA edición del Manual de "
                  "Balanza de Pagos del FMI (MBP6), que es la vigente. Cubre 2010 en "
                  "adelante y se actualiza; es la serie a usar para análisis actual.",
        robustness="green",
    ),
    CanonicalSeries(
        key="balanza_pagos_mbp5", concept="Balanza de pagos (MBP5, histórica)",
        sector="sector_externo",
        source_file="bpagos.xls", base="US$ MM", frequency="anual",
        homogenization="nivel directo; serie DESCONTINUADA",
        rationale="Balanza bajo la QUINTA edición del manual (MBP5). El BCRD dejó de "
                  "actualizar este archivo en 2019: sirve solo para la historia previa a "
                  "2010. NO es comparable ni encadenable con la serie MBP6 — el cambio de "
                  "manual reclasifica bienes para transformación (zonas francas, material "
                  "en RD) y cambia convenciones de la cuenta financiera.",
        robustness="yellow",
    ),
    CanonicalSeries(
        key="remesas", concept="Remesas", sector="sector_externo",
        source_file="Remesas_6.xlsx", base="US$ MM", frequency="mensual",
        homogenization="nivel directo (matriz años×meses)",
        rationale="Mayor flujo externo de divisas del país; soporte del consumo. "
                  "Ojo: las celdas vienen en US$ (no millones pese al rótulo) — verificar unidad.",
        robustness="yellow",  # extrae como matriz; revisar la unidad declarada
    ),
    # Posición de inversión internacional: MISMA situación que la balanza de pagos —
    # dos ediciones del manual del FMI, dos archivos, y estábamos leyendo el viejo.
    CanonicalSeries(
        key="pii_mbp6", concept="Posición de inversión internacional (MBP6, vigente)",
        sector="sector_externo",
        source_file="piianual_6.xlsx", base="US$ MM", frequency="anual",
        homogenization="nivel directo; serie oficial vigente del BCRD",
        rationale="Activos y pasivos externos del país bajo la SEXTA edición del Manual "
                  "de Balanza de Pagos del FMI (MBP6), que es la vigente. Cubre 2009 en "
                  "adelante y se actualiza.",
        robustness="green",
    ),
    CanonicalSeries(
        key="pii_mbp5", concept="Posición de inversión internacional (MBP5, histórica)",
        sector="sector_externo",
        source_file="piianual.xls", base="US$ MM", frequency="anual",
        homogenization="nivel directo",
        rationale="Stock de activos y pasivos externos; solvencia externa.",
        robustness="yellow",
    ),
    # ── Sector Monetario y Financiero ────────────────────────────
    CanonicalSeries(
        key="tpm", concept="Tasa de Política Monetaria", sector="sector_monetario_financiero",
        source_file="Serie_TPM.xlsx", base="%", frequency="mensual",
        homogenization="nivel directo",
        rationale="Instrumento central de política monetaria del BCRD.",
        robustness="green",
    ),
    CanonicalSeries(
        key="agregados_monetarios", concept="Agregados monetarios (M1, M2…)",
        sector="sector_monetario_financiero", source_file="agregados_monetarios.xlsx",
        base="RD$ MM", frequency="mensual", homogenization="nivel directo",
        rationale="Liquidez de la economía; transmisión de la política monetaria.",
        robustness="green",
    ),
    CanonicalSeries(
        key="base_monetaria", concept="Base monetaria", sector="sector_monetario_financiero",
        source_file="base_monetaria.xlsx", base="RD$ MM", frequency="mensual",
        homogenization="nivel directo",
        rationale="Dinero primario emitido por el banco central.",
        robustness="yellow",
    ),
    CanonicalSeries(
        key="tasa_activa", concept="Tasa de interés activa", sector="sector_monetario_financiero",
        source_file="taap_activad.xlsx", base="%", frequency="mensual",
        homogenization="nivel directo",
        rationale="Costo del crédito; el API solo da el último dato → el Excel aporta historia.",
        robustness="yellow", api_series="bcrd.monetarias.tasas_de_interes.activa",
        api_transform="identity",
    ),
    CanonicalSeries(
        key="tasa_pasiva", concept="Tasa de interés pasiva", sector="sector_monetario_financiero",
        source_file="taap_pasivad.xlsx", base="%", frequency="mensual",
        homogenization="nivel directo",
        rationale="Retorno del ahorro; junto con la activa define el spread bancario.",
        robustness="yellow", api_series="bcrd.monetarias.tasas_de_interes.pasiva",
        api_transform="identity",
    ),
    # ── Mercado Cambiario ────────────────────────────────────────
    CanonicalSeries(
        key="tipo_cambio", concept="Tipo de cambio (referencia de mercado)",
        sector="mercado_cambiario", source_file="TASA_DOLAR_REFERENCIA_MC.xlsx",
        base="RD$/US$", frequency="mensual",
        homogenization="el API ya lo trae mensual desde 1991 → preferir el API; Excel para granularidad/pre-1991",
        rationale="Precio de la divisa. La profundidad del API (426 obs) supera a este Excel.",
        robustness="yellow", api_series="bcrd.sector_externo.tasas_de_cambio.venta",
        api_transform="identity",
    ),
    # ── Mercado de Trabajo ───────────────────────────────────────
    CanonicalSeries(
        key="tasa_ocupacion", concept="Tasa de ocupación", sector="mercado_de_trabajo",
        source_file="tasa_ocupacion.xls", base="%", frequency="trimestral",
        homogenization="ojo quiebre ENFT→ENCFT (2021): tratar como dos tramos, no empalmar directo",
        rationale="Mercado laboral. El cambio de encuesta en 2021 no es empalmable sin ajuste.",
        robustness="yellow",
    ),
    CanonicalSeries(
        key="tasa_desocupacion", concept="Tasa de desocupación", sector="mercado_de_trabajo",
        source_file="tasa_desocupacion.xls", base="%", frequency="trimestral",
        homogenization="idem (quiebre ENFT→ENCFT 2021)",
        rationale="Desempleo abierto; indicador social y de holgura del mercado laboral.",
        robustness="yellow",
    ),
    # ── Sector Turismo ───────────────────────────────────────────
    CanonicalSeries(
        key="llegada_turistas", concept="Llegada total de turistas", sector="sector_turismo",
        source_file="lleg_total.xls", base="personas", frequency="mensual",
        homogenization="consolidar los cortes anuales en una sola serie",
        rationale="Flujo turístico, principal generador de divisas; hoy fragmentado por año.",
        robustness="yellow",
    ),
]


# Qué archivos del canónico se PERSISTEN hoy. El registro dice qué series son citables; esto
# dice cuáles de ellas ya se pueden escribir sin degradar la base, que es otra pregunta.
#
# Sale de la corrida en seco del 2026-09-03 (`tasks/INFORME_FASE0_PERSISTENCIA_BCRD.md`):
# de los 26 archivos canónicos, éstos cuatro son los únicos verificados sin colisiones, sin
# huecos, sin nulos internos y —sobre todo— sin duplicados intra-lote que traigan valores
# DISTINTOS para la misma (serie, período). Ese último es el que manda: `_upsert_records`
# resuelve esos empates con "último gana", por orden de lectura y sin dejar marca, y en la
# corrida hubo 29.427 casos repartidos en 176 series de otros cuatro archivos.
#
# ES UNA LISTA TRANSITORIA, y por eso cada exclusión lleva su motivo: una lista blanca sin
# motivo se vuelve permanente por inercia y nadie recuerda qué había que arreglar para
# sacarla. Lo que falta para levantar cada exclusión:
#
#   TASA_DOLAR_REFERENCIA_MC.xlsx — 20.047 empates. Es una serie DIARIA y la identidad de una
#       observación es (series_code, period) con el período en meses: los ~30 días del mes
#       colapsan y sobrevive uno arbitrario. Necesita una decisión de diseño, no un parche.
#   lleg_total.xls  — 4.555 empates en las columnas de tasa de crecimiento.
#   piianual_6.xlsx — 2.970 empates: filas distintas del cuadro colapsan en un mismo código
#   piianual.xls    — 1.855 empates, mismo motivo. Necesitan que el código lleve su sujeto.
#   Los 18 restantes — no evaluados uno a uno todavía; entran cuando se los verifique.
#
# Vacío o None en `ingest_canonical` significa "todo el canónico", que es el comportamiento
# histórico y el que corresponde cuando esta lista deje de hacer falta.
#
# El valor es `None` para habilitar el ARCHIVO ENTERO, o la lista de HOJAS habilitadas cuando
# el libro trae unas que extraen bien y otras que no. Es un solo diccionario y no una lista de
# archivos más un mapa de hojas al lado: dos estructuras que hay que mantener en sincronía se
# desincronizan, y de eso este repo ya tiene lecciones escritas.
#
# Los nombres de hoja son los del libro, tal como los ve quien lo abre en Excel; el prefijo
# del código lo arma el motor con su propio `_slug`.
PERSISTIBLES_VERIFICADOS: Dict[str, Optional[List[str]]] = {
    "pib_2018.xlsx": None,            # PIB real trimestral: 77 trimestres 2007-Q1→2026-Q1
    "imae_2018.xlsx": None,           # IMAE mensual, incluido el índice que consume el nowcast
    "ipc_base_2019-2020.xls": None,   # IPC general: 511 meses desde 1984
    "pib_deflactor_2018.xlsx": None,  # deflactor del PIB: 33 trimestres desde 2018-Q1
    # El PIB por sector de origen entra POR HOJA. Las dos trimestrales extraen limpias —162
    # series, 2018-Q1→2025-Q4, cero duplicados con valores en conflicto—; las dos ACUMULADAS
    # mezclan períodos anuales y trimestrales dentro de la misma serie y producen 1.660
    # duplicados con valores distintos, que el upsert resolvería por orden de lectura.
    # Las cuatro entran: los rótulos del cuadro acumulado (`E-J`/`E-S`/`E-D`) no resolvían
    # trimestre y las tres columnas de cada año colapsaban en la misma clave; corregido en
    # `periods.py`, las cuatro hojas dan 0 duplicados con valores en conflicto y 0 series con
    # períodos mezclados. Las acumuladas declaran su naturaleza en el código —`_acumulado`—
    # y en una nota metodológica que viaja al cliente por la Data API.
    # Se listan LAS CUATRO en vez de poner `None`: el valor es el mismo hoy, pero la lista
    # dice cuáles se verificaron una por una, y si el BCRD agrega una quinta hoja no se
    # habilita sola sin que alguien la mire.
    "pib_origen_2018.xlsx": ["PIB$_Trim", "PIBK_Trim",
                             "PIB$_Trim_Acum", "PIBK_Trim_Acum"],
}


def registry() -> List[CanonicalSeries]:
    return list(REGISTRY)


def as_dicts() -> List[dict]:
    return [asdict(s) for s in REGISTRY]


def by_key(key: str) -> Optional[CanonicalSeries]:
    return next((s for s in REGISTRY if s.key == key), None)
