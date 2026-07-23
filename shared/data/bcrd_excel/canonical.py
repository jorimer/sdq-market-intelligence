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
from typing import List, Optional

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
    "bcrd.xls.bpagos.": (
        "Balanza de pagos bajo el MBP5 (quinta edición del manual) — serie HISTÓRICA y "
        "DESCONTINUADA: el BCRD dejó de actualizar este archivo en 2019. Úsese solo para el "
        "período previo a 2010. NO es comparable ni encadenable con la serie MBP6 "
        "(bcrd.xls.bpagos_6.*): en 2010, el único año que ambas publican, las remesas "
        "difieren 23%."
    ),
}


def note_for(series_code: str) -> str:
    """Nota metodológica de una serie, por prefijo. Cadena vacía si no tiene."""
    for prefix, note in SERIES_NOTES.items():
        if str(series_code).startswith(prefix):
            return note
    return ""


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
        excel_series_suffix="serie_original_variacion_porcentual_interanual",
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
    CanonicalSeries(
        key="pii", concept="Posición de inversión internacional", sector="sector_externo",
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


def registry() -> List[CanonicalSeries]:
    return list(REGISTRY)


def as_dicts() -> List[dict]:
    return [asdict(s) for s in REGISTRY]


def by_key(key: str) -> Optional[CanonicalSeries]:
    return next((s for s in REGISTRY if s.key == key), None)
