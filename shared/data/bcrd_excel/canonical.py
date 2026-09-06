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
    "bcrd.xls.taap_activa.": (
        "Tasa activa promedio ponderada, tramo HISTÓRICO 1998-2007. El BCRD publica esta "
        "serie en CUATRO archivos por período (hasta 2007, 2008-2012, 2013-2016, 2017 en "
        "adelante) y NINGUNO SOLAPA con el siguiente, así que el empalme se DOCUMENTA y NO SE "
        "MIDE contra un período común. Lo que sí se midió: los tres saltos de empalme "
        "(+0,62 · +2,24 · −0,06 pp) caen dentro del movimiento mensual normal de la serie "
        "—mediana 0,49, p90 1,28— y los seis saltos más grandes de los 343 meses ocurren "
        "todos DENTRO de un tramo, ninguno en un empalme. La columna de este tramo se llama "
        "«Promedio» y no «Promedio Ponderado»: se comprobó que NO es el promedio simple de "
        "los plazos (difiere 1,03 pp en media), y que un empalme simple↔ponderado habría "
        "dejado un escalón del orden de 1,8 pp, no de 0,62."
    ),
    "bcrd.xls.taap_pasiva.": (
        "Tasa pasiva promedio ponderada, tramo HISTÓRICO 1998-2007. Misma estructura de "
        "cuatro archivos, ninguno solapa con el siguiente, y mismo criterio: el empalme se "
        "DOCUMENTA y NO SE MIDE contra un período común. Saltos de empalme "
        "−0,25 · +0,42 · +0,15 pp, dentro de su variación mensual normal (mediana 0,36, "
        "p90 1,02). Verificación conjunta: en los 343 meses empalmados el spread "
        "activa−pasiva es SIEMPRE positivo (media 6,50 pp, mínimo 1,66), sin una sola "
        "inversión — un empalme mal armado habría producido al menos una."
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
    # El eje de proyecciones la CITA en su tabla de trayectoria. Antes viajaba como
    # `pib_real` —el nombre de la variable del bloque, feo pero corto—; al resolverse a su
    # código real quedó publicándose la ruta de la hoja de cálculo entera, que es lo que este
    # mapa existe para impedir.
    "bcrd.xls.pib_2018.serie_original_indice": "PIB real (índice de volumen, BCRD)",
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
        # De `yellow` a `green`: el amarillo era del EMPALME —una cautela metodológica sobre
        # cómo encadenar con la serie base—, no de la extracción. Las 25 observaciones
        # (oct-2019 → oct-2021) salen limpias y su variación mensual coincide EXACTO con la
        # de su propio índice en las 24 comparaciones posibles. Que sea una serie puente lo
        # dice su `homogenization`, no este campo.
        robustness="green", api_series="bcrd.ipc.indice", api_transform="yoy",
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
        # A `green`: sus cuatro columnas salían `col2`, `x`, `x_c4` y `x_c5` —el encabezado
        # está por encima de un bloque de cierres anuales y lo que hay justo arriba del
        # primer dato son guiones—. Nombradas bien, la variación mensual coincide EXACTO con
        # la de su índice en las 318 comparaciones.
        # El puente apunta al ÍNDICE, no a ninguna de sus tres variaciones: es el nivel, y
        # la comprobación que lo eligió es que las tres variaciones se derivan de él.
        robustness="green", excel_series_suffix=".ipc_subyacente",
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
        # Este sufijo VOLVIÓ a ser el que el registro declaraba al principio, y la vuelta
        # dice algo. En su momento no resolvía a ninguna serie y se corrigió a
        # `variacion_porcentual_interanual`, eligiendo entre cuatro candidatas por
        # coincidencia CON EL DATO —error 0,00000 pp contra la variación interanual del
        # índice original—. La causa real no era el sufijo: era que el encabezado de TRES
        # niveles se leía mal y nueve de las catorce columnas perdían el nombre de su cuadro
        # (dos ni siquiera se persistían, desempatadas por coordenada). Leído bien, la
        # declaración original vuelve a valer y es única. Un puente que no resuelve puede
        # estar acusando al extractor, no al registro. Lo vigila
        # `tests/test_puentes_canonicos.py`, que además re-verifica la identidad numérica.
        excel_series_suffix="serie_original_variacion_porcentual_interanual",
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
        # A `green`, por el mismo criterio que `pii_mbp5`: el amarillo hablaba de
        # METODOLOGÍA —que la serie está descontinuada y no se encadena—, y eso ya lo dice su
        # nota, que viaja al cliente por la Data API. La extracción es limpia: 54 series,
        # 0 duplicados en conflicto, y las sub-filas repetidas («Nacionales», «Zonas
        # Francas», que cuelgan tanto de exportaciones como de importaciones) ya se
        # califican las dos.
        robustness="green",
    ),
    CanonicalSeries(
        key="remesas", concept="Remesas", sector="sector_externo",
        source_file="Remesas_6.xlsx", base="US$ MM", frequency="mensual",
        homogenization="nivel directo (matriz años×meses)",
        rationale="Mayor flujo externo de divisas del país; soporte del consumo. La hoja se "
                  "titula «MILLONES DE US$» y las celdas están en US$: la unidad se corrige "
                  "en `UNIDADES_CURADAS`, verificada contra la balanza de pagos del propio "
                  "BCRD (2010 = 3.683 millones, y los doce meses suman 3.682.932.483).",
        # A `green`: la duda que sostenía el amarillo era la unidad, y quedó resuelta con una
        # comprobación contra otra publicación del emisor, no con una impresión.
        # El puente no era una decisión de analista: el archivo produce UNA sola serie.
        robustness="green", excel_series_suffix=".valor",
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
        homogenization="nivel directo; cada año trae el saldo de apertura, cuatro flujos "
                       "(transacciones, tipo de cambio, precios, otras) y el de cierre",
        rationale="Stock de activos y pasivos externos; solvencia externa.",
        # VERDE desde el 2026-09-04. Era amarillo porque el archivo NO extraía bien: sus seis
        # conceptos por año colapsaban en uno y los flujos salían corridos un año. Corregido,
        # la identidad contable del propio cuadro —cierre = apertura + los cuatro flujos—
        # cierra en 768 casos y falla en cero. `robustness` describe la EXTRACCIÓN; que la
        # serie esté descontinuada lo dice su nota metodológica, no este campo.
        robustness="green",
    ),
    # ── Sector Monetario y Financiero ────────────────────────────
    CanonicalSeries(
        key="tpm", concept="Tasa de Política Monetaria", sector="sector_monetario_financiero",
        source_file="Serie_TPM.xlsx", base="%", frequency="mensual",
        homogenization="nivel directo",
        rationale="Instrumento central de política monetaria del BCRD.",
        # De las tres series del archivo (TPM, lombarda y facilidad de depósito), la TPM se
        # nombra sola: no hay elección que hacer.
        robustness="green", excel_series_suffix=".tasa_de_politica_monetaria",
    ),
    # La CURVA SOBERANA EN PESOS, del cuadro V.1 «Valores subastados del Banco Central en
    # moneda nacional». Se declara el término largo y el de uno a dos años, que son los dos
    # que una valuación necesita; los plazos cortos y los montos entran igual al corpus por
    # el archivo, pero no se nombran acá porque nombrarlo todo sin uso es inventario.
    #
    # POR QUÉ IMPORTA, y no es un matiz: el valuador necesita una tasa libre de riesgo LARGA
    # en pesos. La TPM es overnight y está en 5,25 % contra una inflación de 5,47 %, así que
    # usarla a diez años daría una tasa real NEGATIVA y el modelo diría que casi cualquier
    # entidad crea valor. El término de más de dos años está en 9,78 %: son 453 puntos
    # básicos de diferencia, que a un ROE típico de 13 % es la línea entre crear y destruir.
    CanonicalSeries(
        key="curva_pesos_mas_de_dos_anos",
        concept="Curva soberana en pesos · término de más de dos años",
        sector="sector_monetario_financiero", source_file="valores_bc_mn.xlsx",
        base="%", frequency="mensual", homogenization="nivel directo",
        rationale=("Tasa libre de riesgo LARGA en pesos: el insumo de `Ke` en el eje de "
                   "valuación. Una tasa overnight no puede descontar un flujo perpetuo."),
        robustness="green", excel_series_suffix=".mas_de_dos_anos",
    ),
    CanonicalSeries(
        key="curva_pesos_de_1_a_2_anos",
        concept="Curva soberana en pesos · término de uno a dos años",
        sector="sector_monetario_financiero", source_file="valores_bc_mn.xlsx",
        base="%", frequency="mensual", homogenization="nivel directo",
        rationale=("El tramo intermedio de la curva. Con el término largo da la PENDIENTE, "
                   "que es lo que dice si el mercado espera que la tasa suba o baje."),
        robustness="green", excel_series_suffix=".de_1_a_2_anos",
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
        # A `green`: sus catorce columnas salían con el NÚMERO DE LÍNEA del emisor por
        # nombre —`me_9`, `me_11`, `valores_3`— porque la fila de referencias `(1)`…`(14)`,
        # con la que el BCRD escribe sus propias sumas, contaba como rótulo y tapaba la
        # cadena de grupos de arriba. Con eso corregido, la IDENTIDAD CONTABLE del cuadro
        # cierra EXACTO en los dos niveles y en los 290 meses: restringida = (1)+(2)+(3), y
        # amplia = restringida + los nueve componentes.
        robustness="green",
    ),
    CanonicalSeries(
        key="tasa_activa", concept="Tasa de interés activa", sector="sector_monetario_financiero",
        source_file="taap_activad.xlsx", base="%", frequency="mensual",
        homogenization="nivel directo",
        rationale="Costo del crédito; el API solo da el último dato → el Excel aporta historia.",
        # A `green`: la hoja declara 256 columnas y el cuadro termina en la 15; el relleno
        # heredaba el rótulo del último grupo. Corregido, las 15 series salen con 0
        # duplicados en conflicto y el promedio ponderado cae entre el mínimo y el máximo de
        # los plazos en los 115 meses.
        #
        # El puente estaba sin declarar «porque la elección entre promedio simple y ponderado
        # era una decisión de método pendiente». La decisión la resolvió el EMPALME: los tres
        # tramos históricos apuntan al ponderado, y declararlo en ellos y no acá dejaría la
        # serie imposible de armar. Es el ponderado, y ahora se dice.
        robustness="green", excel_series_suffix=".promedio_ponderado",
        api_series="bcrd.monetarias.tasas_de_interes.activa",
        api_transform="identity",
    ),
    # Los TRES tramos históricos de cada tasa. El BCRD publica activa y pasiva en cuatro
    # archivos por período, y el registro solo declaraba el vigente (2017→): la serie
    # empezaba en 2017 y el bloque del BVAR se quedaba sin la crisis de 2003, que es el
    # episodio de estrés más informativo que tiene el país. Con los cuatro tramos son 343
    # meses, 1998-01 → 2026-07. El empalme se declara en `SERIES_NOTES`.
    CanonicalSeries(
        key="tasa_activa_1998_2007", concept="Tasa de interés activa (tramo 1998-2007)",
        sector="sector_monetario_financiero", source_file="taap_activa.xls", base="%",
        frequency="mensual",
        homogenization="tramo del empalme; ver la nota metodológica del prefijo",
        rationale="Contiene la crisis bancaria de 2003-2004, cuando la tasa activa pasó de "
                  "20% a 27,5% y volvió a 15% en tres años. Un modelo entrenado solo desde "
                  "2008 nunca vio un episodio así.",
        robustness="green", excel_series_suffix="p_l_a_z_o_s_promedio",
    ),
    CanonicalSeries(
        key="tasa_activa_2008_2012", concept="Tasa de interés activa (tramo 2008-2012)",
        sector="sector_monetario_financiero", source_file="taap_activad-2008-2012.xls",
        base="%", frequency="mensual",
        homogenization="tramo del empalme; ver la nota metodológica del prefijo",
        rationale="Cubre la crisis financiera global y su transmisión al costo del crédito.",
        robustness="green", excel_series_suffix=".promedio_ponderado",
    ),
    CanonicalSeries(
        key="tasa_activa_2013_2016", concept="Tasa de interés activa (tramo 2013-2016)",
        sector="sector_monetario_financiero", source_file="taap_activad-2013-2016.xlsx",
        base="%", frequency="mensual",
        homogenization="tramo del empalme; ver la nota metodológica del prefijo",
        rationale="Cierra el hueco entre el tramo de la crisis y el archivo vigente.",
        robustness="green", excel_series_suffix=".promedio_ponderado",
    ),
    CanonicalSeries(
        key="tasa_pasiva_1998_2007", concept="Tasa de interés pasiva (tramo 1998-2007)",
        sector="sector_monetario_financiero", source_file="taap_pasiva.xls", base="%",
        frequency="mensual",
        homogenization="tramo del empalme; ver la nota metodológica del prefijo",
        rationale="El otro lado del spread en la crisis de 2003: la tasa pasiva se disparó "
                  "con la corrida y el spread se comprimió a 1,66 pp.",
        robustness="green", excel_series_suffix=".promedio",
    ),
    CanonicalSeries(
        key="tasa_pasiva_2008_2012", concept="Tasa de interés pasiva (tramo 2008-2012)",
        sector="sector_monetario_financiero", source_file="taap_pasivad-2008-2012.xls",
        base="%", frequency="mensual",
        homogenization="tramo del empalme; ver la nota metodológica del prefijo",
        rationale="Contraparte pasiva del tramo 2008-2012 de la activa.",
        robustness="green", excel_series_suffix=".promedio_ponderado",
    ),
    CanonicalSeries(
        key="tasa_pasiva_2013_2016", concept="Tasa de interés pasiva (tramo 2013-2016)",
        sector="sector_monetario_financiero", source_file="taap_pasivad-2013-2016.xlsx",
        base="%", frequency="mensual",
        homogenization="tramo del empalme; ver la nota metodológica del prefijo",
        rationale="Contraparte pasiva del tramo 2013-2016 de la activa.",
        robustness="green", excel_series_suffix=".promedio_ponderado",
    ),
    CanonicalSeries(
        key="tasa_pasiva", concept="Tasa de interés pasiva", sector="sector_monetario_financiero",
        source_file="taap_pasivad.xlsx", base="%", frequency="mensual",
        homogenization="nivel directo",
        rationale="Retorno del ahorro; junto con la activa define el spread bancario.",
        # A `green`: mismo defecto y misma comprobación que la activa. Traía 27.715
        # observaciones nulas de más —las 241 columnas de relleno heredaban «Interbancaria»—
        # y ahora son 1.610 claves, todas distintas. Y mismo puente, por el mismo motivo: lo
        # fija el empalme con los tres tramos históricos.
        robustness="green", excel_series_suffix=".promedio_ponderado",
        api_series="bcrd.monetarias.tasas_de_interes.pasiva",
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
        # `frequency` decía «trimestral» y el archivo no publica un solo trimestre: trae
        # «Anual 1960-1984», «Anual 1991-2016» y «Semestral 2000-2016» (las encuestas de
        # abril y octubre). Medido, no supuesto — 83 observaciones, ninguna trimestral.
        source_file="tasa_ocupacion.xls", base="%", frequency="anual",
        homogenization="ojo quiebre ENFT→ENCFT (2021): tratar como dos tramos, no empalmar directo",
        rationale="Mercado laboral. El cambio de encuesta en 2021 no es empalmable sin ajuste.",
        robustness="yellow",
    ),
    CanonicalSeries(
        key="tasa_desocupacion", concept="Tasa de desocupación", sector="mercado_de_trabajo",
        # Igual que la de ocupación: dos hojas anuales y dos semestrales (abril y octubre),
        # 125 observaciones, cero trimestrales. La declaración decía «trimestral».
        source_file="tasa_desocupacion.xls", base="%", frequency="anual",
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
#   Los 16 restantes — no evaluados uno a uno todavía; entran cuando se los verifique.
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
#: Unidades CURADAS: los casos en que el emisor rotuló mal su propia planilla, con la
#: verificación que lo demuestra al lado. La regla general no cambia —la unidad la declara
#: el emisor y `series_nature` se construyó sobre eso—; esto es la excepción, y para entrar
#: exige una comprobación CONTRA OTRA PUBLICACIÓN DEL MISMO EMISOR, escrita acá. Una unidad
#: no se corrige porque el número «se ve raro».
#:
#: Clave: prefijo del código de serie. Valor: (unidad correcta, evidencia).
UNIDADES_CURADAS: Dict[str, tuple] = {
    "bcrd.xls.remesas_6.": (
        "US$",
        "La hoja se titula «MILLONES DE US$» y trae 280.155.040 para enero de 2010: juntas, "
        "las dos cosas dirían 280 billones de dólares en un mes. La suma de los doce meses "
        "de 2010 da 3.682.932.483, y la balanza de pagos MBP6 del propio BCRD publica "
        "remesas 2010 = 3.683 millones de US$. Las celdas están en US$ y el rótulo se "
        "equivoca por un factor de un millón.",
    ),
}


#: Escalas CURADAS: los archivos que guardan una tasa como FRACCIÓN mientras su encabezado
#: dice porcentaje. Excel almacena una celda con formato de porcentaje como la fracción
#: —0,0525 se muestra «5,25%» pero el valor guardado es 0,0525— y el extractor lee el valor
#: crudo, así que el formato se pierde.
#:
#: Multiplicar valores es más peligroso que corregir una etiqueta, así que cada entrada trae
#: TRES cosas: el factor, un TOPE por encima del cual no se aplica —el freno que impide
#: volver a multiplicar si algún día la fuente republica ya en porcentaje— y la evidencia.
#:
#: Clave: prefijo del código. Valor: (factor, tope, evidencia).
ESCALAS_CURADAS: Dict[str, tuple] = {
    # Las TASAS del cuadro de valores subastados vienen en fracción, igual que el archivo de
    # la TPM. El tope de 1.5 es lo que hace la corrección idempotente: una tasa ya en
    # por-ciento (7,00) queda intacta, y una en fracción (0,07) se multiplica. Sin él, una
    # republicación del BCRD en por-ciento se multiplicaría dos veces.
    #
    # OJO — el prefijo apunta a `tasa`, NO al archivo entero: el mismo cuadro trae los MONTOS
    # subastados, que son miles de millones de pesos. Multiplicarlos por cien los convertiría
    # en una cifra absurda sin que nada falle, porque el tope solo mira si el valor es chico.
    # Los DOS plazos largos pierden el prefijo «tasa de interés» al extraerse —el
    # super-encabezado del cuadro no los alcanza— y quedan como `de_1_a_2_anos` y
    # `mas_de_dos_anos`. Se nombran uno por uno en vez de ensanchar el prefijo al archivo:
    # ensancharlo pondría los MONTOS bajo la misma regla, y aunque el tope de 1.5 los
    # protege hoy, protege por el TAMAÑO del valor y no por lo que la serie ES — un monto
    # subastado de cero o de un peso caería adentro. Y son justo los dos plazos que el
    # costo de capital necesita: sin ellos la corrección falla en silencio donde más duele.
    "bcrd.xls.valores_bc_mn.de_1_a_2_anos": (
        100.0, 1.5, "Plazo de 1 a 2 años del cuadro V.1; misma escala fraccionaria que el "
                    "resto de las tasas del archivo.",
    ),
    "bcrd.xls.valores_bc_mn.mas_de_dos_anos": (
        100.0, 1.5, "Plazo de más de dos años del cuadro V.1 — el término largo de la curva "
                    "en pesos, y el insumo del costo de capital. Misma escala fraccionaria.",
    ),
    "bcrd.xls.valores_bc_mn.tasa": (
        100.0, 1.5,
        "El cuadro V.1 «Valores subastados del Banco Central» guarda fracciones: en 2026-07 "
        "el plazo de más de dos años venía como 0,0978. Verificado contra el propio archivo, "
        "que trae la TPM en la misma escala (0,0525) y que a ×100 reproduce el 5,25% "
        "publicado; y contra el sentido de la curva, que a ×100 queda creciente y coherente "
        "—7,00% a 30 días, 9,78% a más de dos años— mientras que en fracción daría una curva "
        "de 0,07% a 0,10%, que no existe en ningún mercado.",
    ),
    "bcrd.xls.serie_tpm.": (
        100.0, 1.5,
        "El archivo se titula «En % anual» y guarda fracciones. Verificado por tres caminos: "
        "en 2026-07 la TPM se persistía como 0,0525 mientras la tasa pasiva promedio del "
        "sistema es 6,90% —una tasa de política de 0,05% con depósitos al 6,9% no existe, el "
        "arbitraje la cerraría el mismo día—; la facilidad permanente de depósito, que es el "
        "piso del corredor, venía como 0,045, en la misma escala, de modo que el corredor "
        "solo es coherente a ×100; y el máximo de la serie es 0,5, que a ×100 da el 50% real "
        "de la TPM dominicana tras la crisis de 2003-2004.",
    ),
}


def escala_curada(series_code: str, valor: Optional[float]) -> Optional[float]:
    """El valor con su escala corregida, o el mismo valor si no hay nada que corregir.

    El TOPE no es cosmético: si el BCRD republica el archivo ya en porcentaje, volver a
    multiplicar daría 525%. Una fracción de tasa vive por debajo del tope; un porcentaje, no.
    """
    if valor is None:
        return None
    for prefijo, (factor, tope, _evidencia) in ESCALAS_CURADAS.items():
        if str(series_code).startswith(prefijo) and abs(float(valor)) < tope:
            return float(valor) * factor
    return valor


def unidad_curada(series_code: str) -> Optional[str]:
    """La unidad verificada de una serie cuando el emisor rotuló mal, o ``None``."""
    for prefijo, (unidad, _evidencia) in UNIDADES_CURADAS.items():
        if str(series_code).startswith(prefijo):
            return unidad
    return None


PERSISTIBLES_VERIFICADOS: Dict[str, Optional[List[str]]] = {
    # El cuadro V.1 «Valores subastados del Banco Central en moneda nacional». Es la CURVA
    # SOBERANA EN PESOS, y de acá sale la tasa libre de riesgo larga que el costo de capital
    # necesita: el término de más de dos años está en 9,78 % contra una TPM overnight de
    # 5,25 %, y usar la TPM subestimaría `Ke` en 453 puntos básicos.
    #
    # Entra ahora y no antes porque hasta ahora no extraía bien, y las dos cosas que fallaban
    # ya están arregladas y medidas:
    #   · once filas de 2005 se estampaban como 2004 —el BCRD escribió «01» en la columna de
    #     año— perdiendo once meses y duplicando otros once. El arrastre del año ahora solo
    #     opera sobre una celda VACÍA.
    #   · tres columnas quedaban fuera por medir la densidad solo en las primeras 80 filas.
    #     Corregido a la unión de las dos ventanas; estas tres siguen fuera y con razón —10 %,
    #     32 % y 39 % de densidad sobre el archivo entero, contra el 40 % que se exige—: son
    #     MONTOS de plazos que el BCRD casi no subastó, y ninguna es la serie de la curva.
    #
    # Verificado sobre el archivo vigente: 12 series, 279 meses 2001-12→2026-07, **0
    # duplicados con valores en conflicto** (eran 99) y 0 avisos de truncamiento.
    "valores_bc_mn.xlsx": None,
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
    # El tipo de cambio, con sus SIETE cortes. Tenía dos defectos distintos y los dos eran
    # del parser: la hoja `Diaria` es una serie diaria de verdad —`Año | Mes | Día`— y el
    # período no tenía día, así que los ~22 días hábiles de cada mes colapsaban; y los cortes
    # trimestrales rotulan el trimestre con los meses completos (`Enero-Marzo`), grafía que
    # el mapa no tenía. Con las dos cosas corregidas, las siete hojas dan 0 duplicados con
    # valores en conflicto.
    "TASA_DOLAR_REFERENCIA_MC.xlsx": ["Diaria", "PromMensual", "PromTrimestral", "PromAnual",
                                      "FPMensual", "FPTrimestral", "FPAnual"],
    # La posición de inversión internacional, los dos manuales. Bajo cada año el cuadro trae
    # SEIS conceptos —saldo de apertura, cuatro flujos y saldo de cierre— y el motor no sabía
    # leer un sub-encabezado que no fuera un período: los seis caían en el mismo (serie, año).
    # Además tomaba como fila de años la de FECHAS de corte, así que los flujos salían
    # corridos un año. Con las dos cosas corregidas, la IDENTIDAD CONTABLE del propio cuadro
    # —cierre = apertura + los cuatro flujos— cierra en 2.718 casos y falla en cero.
    "piianual_6.xlsx": None,
    # El MBP5 va POR HOJA porque su entrada es `yellow`, y con razón: es la serie histórica y
    # DESCONTINUADA, que su propia nota manda usar solo antes de 2010. Ese amarillo habla de
    # metodología, no de extracción — la hoja extrae limpia y la identidad contable cierra.
    "piianual.xls": None,
    # Las llegadas de pasajeros, por HOJA: su entrada sigue en `yellow` y con razón, pero por
    # HOMOGENEIZACIÓN —el archivo publica varios cortes de años como hojas separadas y falta
    # consolidarlos—, no por extracción. Las cuatro hojas dan 0 duplicados con valores en
    # conflicto, 0 series con períodos mezclados y 0 códigos desempatados por coordenada.
    "lleg_total.xls": ["No Residentes 78 - 26", " Residentes 93 - 26",
                       "Llegada total 93-26", "1993 - 2026"],
    # ── Los 18 restantes, triados uno por uno contra los seis criterios ──────────────
    # Los seis: 0 duplicados (serie, período) con valores en conflicto · 0 series con formas
    # de período mezcladas · 0 códigos desempatados por coordenada · 0 avisos de truncamiento
    # · 0 discrepancias de cadencia contra el registro · y una verificación de SENTIDO propia
    # del archivo, que es la que distingue «no hay conflictos» de «está bien leído».
    #
    # Precios. Las doce «Var. %» del IPC por grupos se comprobaron contra la variación
    # mensual de su propio índice: once cierran EXACTO (0,000000) y la de alimentos difiere
    # 0,0038 pp en un mes de 330 — redondeo del emisor, no un parse. Las de quintiles y
    # regiones ya estaban verificadas así cuando se arregló `_grupo_a_la_izquierda`.
    "ipc_grupos_base_2019-2020.xls": None,
    "ipc_quintiles_base_2019-2020.xls": None,
    "ipc_regiones_base_2019-2020.xls": None,
    # El subyacente publica un bloque de cierres anuales ENTRE el encabezado y la serie
    # mensual: el buscador de nombres miraba las seis filas de encima del primer dato, ahí
    # solo hay guiones, y las cuatro series salían `col2`, `x`, `x_c4`, `x_c5` (dos de ellas
    # ni se persistían). Corregido, su variación mensual cierra exacto contra su índice en
    # las 318 comparaciones.
    "ipc_subyacente_base_2019-2020.xlsx": None,
    # La serie referencial son 25 meses (oct-2019 → oct-2021) y eso NO es una lectura corta:
    # es el empalme de la base nueva y el archivo no publica más. Variación mensual contra
    # índice: 24 de 24 exactas.
    "ipc_base_2019-2020_serie_referencial.xlsx": None,
    "Costo_Canasta_quintiles_base_2019-2020.xlsx": None,
    # Sector externo. `bpagos` y `bpagos_6` tienen «Nacionales» y «Zonas Francas» dos veces
    # —bajo exportaciones y bajo importaciones— sin numeración ni sangría que las ordene, y
    # solo la SEGUNDA se desempataba: la primera quedaba como `balanza_de_bienes.nacionales`
    # al lado de una que sí decía «importaciones». Ahora se califican las dos.
    "bpagos_6.xls": None,
    "bpagos.xls": None,
    "reservas_internacionales.xlsx": None,   # netas ≤ brutas en los 284 meses comunes
    # Las remesas entran con la unidad CORREGIDA: la hoja dice «MILLONES DE US$» y las celdas
    # están en US$. Ver `UNIDADES_CURADAS`, que trae la verificación contra la balanza de
    # pagos del propio BCRD.
    "Remesas_6.xlsx": None,
    # Sector monetario. Las pasivas tenían 27.715 observaciones nulas de más: la hoja declara
    # 256 columnas, el cuadro termina en la 14 —«Interbancaria», un grupo sin métrica
    # propia— y las 241 vacías heredaban ese nombre. No producía conflicto de valores, así
    # que ningún criterio lo veía; lo delató la densidad, ×18,21 filas por clave. Verificado
    # además que el promedio ponderado cae entre el mínimo y el máximo de los plazos en los
    # 115 meses.
    "taap_pasivad.xlsx": None,
    "taap_activad.xlsx": None,
    # Los tres tramos históricos de cada tasa, triados con los mismos seis criterios: los
    # seis dan densidad ×1,00, 0 duplicados en conflicto, 0 series con períodos mezclados,
    # 0 códigos por coordenada y 0 avisos de truncamiento. Verificación de sentido conjunta:
    # en los 343 meses empalmados el spread activa−pasiva es siempre positivo, sin una sola
    # inversión.
    "taap_activa.xls": None,
    "taap_activad-2008-2012.xls": None,
    "taap_activad-2013-2016.xlsx": None,
    "taap_pasiva.xls": None,
    "taap_pasivad-2008-2012.xls": None,
    "taap_pasivad-2013-2016.xlsx": None,
    "Serie_TPM.xlsx": None,
    "agregados_monetarios.xlsx": None,
    "base_monetaria.xlsx": None,
    # Sector real. El PIB por gasto es el archivo que destapó el falso positivo del guard de
    # truncamiento: sus «22 columnas con dato sin leer» eran un segundo cuadro de tasas de
    # crecimiento, no una lectura corta.
    # El PIB por gasto sigue `yellow` —los dos cuadros por hoja mezclan niveles y
    # ponderaciones, y falta decidir qué serie del archivo es la canónica: la entrada
    # `pib_nominal_gasto` no declara puente—, así que entra POR HOJA, que son las dos que
    # tiene. Es el archivo que destapó el falso positivo del guard de truncamiento: sus «22
    # columnas con dato sin leer» eran un segundo cuadro de tasas de crecimiento.
    "pib_gasto.xls": ["Valores Corrientes", "Valores Encadenados"],
    # Mercado de trabajo. Las dos son series DESCONTINUADAS (terminan en 2016) y su entrada
    # sigue en `yellow` por eso, no por extracción. Su `frequency` decía «trimestral» y el
    # archivo no publica un solo trimestre — corregido a «anual» con la evidencia al lado de
    # cada entrada. La hoja semestral de ocupación tenía la única serie del archivo llamada
    # `col2`: el título del cuadro está dos columnas a la izquierda porque las dos de en
    # medio son ejes (año y semestre).
    # Las dos entran POR HOJA y su entrada sigue `yellow`: son series DESCONTINUADAS
    # (terminan en 2016) y el archivo publica cortes anuales y semestrales que habría que
    # consolidar antes de citarlos como una sola serie. El amarillo es de homogeneización,
    # no de extracción — las siete hojas salen limpias.
    "tasa_ocupacion.xls": ["Anual 1960-1984", "Anual 1991-2016", "Semestral 2000-2016"],
    "tasa_desocupacion.xls": ["Anual 1960-1990", "Anual 1991-2016",
                              " Semestral Abril 2000-2016", "Semestral Octubre 2000-2016"],
}


def codigo_de(entrada: CanonicalSeries, codigos) -> Optional[str]:
    """El `series_code` al que apunta el puente de *entrada*, o ``None``.

    El sufijo identifica DENTRO del archivo de la entrada, no en todo el corpus, y resolverlo
    globalmente devuelve la serie equivocada: `serie_original_indice` existe en el PIB y en el
    IMAE, y `quintil_3` en el IPC por quintiles y en el costo de la canasta — cinco de los
    treinta y cuatro puentes colisionan así. Por eso el emparejamiento se acota al prefijo del
    `source_file`, que es el otro campo que la entrada ya declara.

    Devuelve ``None`` si la entrada no tiene puente o si el sufijo no resuelve a EXACTAMENTE
    una serie: dos es tan poco útil como cero, y elegir una sería adivinar.
    """
    from .extract import default_prefix

    if not entrada.excel_series_suffix:
        return None
    prefijo = default_prefix(entrada.source_file) + "."
    hits = [c for c in codigos
            if str(c).startswith(prefijo) and str(c).endswith(entrada.excel_series_suffix)]
    return hits[0] if len(hits) == 1 else None


def registry() -> List[CanonicalSeries]:
    return list(REGISTRY)


def as_dicts() -> List[dict]:
    return [asdict(s) for s in REGISTRY]


def by_key(key: str) -> Optional[CanonicalSeries]:
    return next((s for s in REGISTRY if s.key == key), None)
