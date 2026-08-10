"""Extract insurer financials from the SIS audited-statements Excel (por cía).

Source: ``Estados-Financieros-Auditados-por-cia-<year>.xlsx`` (SIS transparencia),
one **sheet per insurer**, each a regulatory chart of accounts:
``[CTAS, DESCRIPCION, <year>, <year-1>]``. Sections by 1-digit code:
``1 ACTIVO · 2 PASIVO · 3 CAPITAL/PATRIMONIO · 4 INGRESOS · 5 GASTOS``.

Deterministic, reconciled parse — NO OCR (the file is clean Excel):
  * Balance-sheet totals = sum of the 4-digit **leaf** accounts under each section
    (contra-accounts are already negative). Reconciled: |activo − pasivo −
    patrimonio| / activo must be < 1% or the sheet is flagged (fail-soft: returned
    with ``reconciled=False``, never silently trusted).
  * Income statement uses 6-digit per-ramo leaves under 4-digit sub-headers:
      - primas suscritas (direct) = Σ children of sub-headers "PRIMAS SUSCRITAS"
      - siniestros pagados = Σ children of "RECLAMACIONES PAGADAS POR SINIESTRO"
  * Liquidity inputs: inversiones (11xx) + efectivo (12xx); reservas técnicas
    (21xx + 22xx).

Missing values stay ``None`` — never interpolated.
"""
import io
import logging
import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

logger = logging.getLogger("sdq.insurance_intel.audited")


@dataclass
class InsurerFinancials:
    name: str
    slug: str
    period: str                 # the year, "2024"
    activos: Optional[float]
    pasivos: Optional[float]
    patrimonio: Optional[float]
    reservas_tecnicas: Optional[float]
    activos_liquidos: Optional[float]
    primas: Optional[float]      # primas suscritas directas
    siniestros: Optional[float]  # reclamaciones pagadas por siniestro (directo)
    ingresos: Optional[float]
    gastos: Optional[float]
    gastos_operativos: Optional[float]       # comisiones + G&A + otros gastos de operación
    primas_cedidas: Optional[float]          # prima cedida al reasegurador (seguro directo)
    recuperables_reaseguro: Optional[float]  # siniestros a cargo de reaseguradores
    # ── Base DEVENGADA / INCURRIDA (revisión actuarial 2026-08) ──────────────────
    # El catálogo tiene la estructura constitución/liberación: la reserva del PRESENTE
    # ejercicio se carga en la sección 5 y la del ejercicio ANTERIOR se abona en la 4.
    # Con las dos mitades, prima devengada y siniestro incurrido son computables — y
    # siempre lo fueron; el extractor solo tomaba el lado pagado.
    primas_devengadas: Optional[float]     # escrita + reserva riesgos en curso liberada − constituida
    siniestros_incurridos: Optional[float]  # pagado + otras prestaciones + Δreserva específica − salvamentos
    otras_prestaciones: Optional[float]     # 5102 — prestación PAGADA que no estaba en el numerador
    salvamentos: Optional[float]            # 4309 — recupero que reduce el costo de siniestro
    # {ramo: {"primas": x, "siniestros": y}} — y es None cuando el catálogo no lo abre.
    por_ramo: Dict[str, Dict[str, Optional[float]]]
    reconciled: bool

    def as_series(self) -> Dict[str, Optional[float]]:
        """The per-insurer series persisted to ``insurance_series`` (entity_slug set)."""
        return {
            "activos_totales": self.activos,
            "pasivos_totales": self.pasivos,
            "patrimonio": self.patrimonio,
            "reservas_tecnicas": self.reservas_tecnicas,
            "activos_liquidos": self.activos_liquidos,
            "primas_suscritas": self.primas,
            "siniestros_pagados": self.siniestros,
            "ingresos_totales": self.ingresos,
            "gastos_totales": self.gastos,
            "gastos_operativos": self.gastos_operativos,
            "primas_cedidas": self.primas_cedidas,
            "recuperables_reaseguro": self.recuperables_reaseguro,
            "primas_devengadas": self.primas_devengadas,
            "siniestros_incurridos": self.siniestros_incurridos,
            "otras_prestaciones": self.otras_prestaciones,
            "salvamentos": self.salvamentos,
        }


# ── Desglose por RAMO (spec §5.6) ──────────────────────────────────────────────
#
# Los leaves de 6 dígitos bajo los sub-headers de primas y siniestros son el desglose por
# ramo del catálogo regulatorio. En SEGUROS GENERALES el sufijo de dos dígitos parea directo
# (``4301XX`` primas ↔ ``5301XX`` siniestros, los mismos 15 ramos). En PERSONAS no: primas
# tiene 8 sub-cuentas y siniestros solo 5, con otro orden — vida individual se abre en
# "primer año" y "renovación" del lado de las primas y se consolida del lado de los
# siniestros. Emparejar por posición daría un loss ratio de vida contra siniestros de
# accidentes, así que el mapeo va explícito.
RAMOS_GENERALES = {
    "01": "incendio_no_catastrofico", "02": "incendio_catastrofico",
    "03": "naves_maritimas", "04": "naves_aereas", "05": "transporte",
    "06": "vehiculos_motor", "07": "agricola_pecuario", "08": "responsabilidad_civil",
    "09": "ramos_tecnicos", "10": "otros_seguros", "11": "fianzas_fidelidad",
    "12": "fianzas_construccion", "13": "fianzas_aduanales", "14": "fianzas_judiciales",
    "15": "otras_fianzas",
}
# ramo → (sufijos de primas 4101, sufijo de siniestros 5101)
RAMOS_PERSONAS = {
    "vida_individual": (("01", "02"), "01"),   # primer año + renovación → vida individual
    "vida_colectivo": (("03",), "02"),
    "accidentes_personales": (("04",), "03"),
    "invalidez": (("05",), "04"),
    "salud": (("07",), "05"),
    # Rentas (06) y otros seguros de personas (08) no tienen contraparte de siniestros en el
    # catálogo: se exponen con primas y ``siniestros=None``, nunca con un cero fabricado.
    "rentas": (("06",), None),
    "otros_personas": (("08",), None),
}


def slugify_insurer(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"\b(s\.?\s?a\.?|c\.?\s?por\.?\s?a\.?|comp(a|añia|ania)?|de seguros|seguros)\b",
               " ", s, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "aseguradora"


def _to_num(v) -> Optional[float]:
    try:
        import math
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _extract_sheet(rows: List[tuple], name: str, period: str) -> Optional[InsurerFinancials]:
    """Extract one insurer sheet from ``[(cta, desc, cur), ...]``. None if not a
    financial-statement sheet (no ACTIVO section)."""
    cta = {}       # code -> value (leaf)
    desc_by_code = {}
    codes_present = set()
    for c, d, v in rows:
        c = str(c).strip()
        codes_present.add(c)
        desc_by_code[c] = str(d).strip().upper()
        n = _to_num(v)
        if n is not None:
            cta[c] = n

    if "1" not in codes_present or "3" not in codes_present:
        return None  # not a statement sheet

    def leaves_sum(prefix: str, ndig: int = 4) -> Optional[float]:
        vals = [v for c, v in cta.items()
                if len(c) == ndig and c.isdigit() and c.startswith(prefix)]
        return round(sum(vals), 2) if vals else None

    def children_sum_where(desc_kw: str) -> Optional[float]:
        """Σ of 6-digit leaves under any 4-digit sub-header whose desc contains kw."""
        heads = [c for c in codes_present
                 if len(c) == 4 and c.isdigit() and desc_kw in desc_by_code.get(c, "")]
        total, seen = 0.0, False
        for h in heads:
            for c, v in cta.items():
                if len(c) == 6 and c.isdigit() and c.startswith(h):
                    total += v
                    seen = True
        return round(total, 2) if seen else None

    def heads_sum(prefixes: tuple, *desc_kws: str,
                  excl: tuple = ()) -> Optional[float]:
        """Σ of 6-digit leaves under 4-digit sub-headers whose code starts with one of
        *prefixes* (the section, e.g. ``51``/``53`` = seguro DIRECTO) and whose description
        contains ALL of *desc_kws* and NONE of *excl*. Selecting by section keeps numerator
        and denominator on the same book: the ISF's premiums are direct, so its costs must
        be direct too. ``excl`` mantiene la medida BRUTA: las cuentas "A CARGO DE
        REASEGURADORES" son la contrapartida cedida y no van del lado bruto."""
        heads = [c for c in codes_present
                 if len(c) == 4 and c.isdigit() and c.startswith(prefixes)
                 and all(k in desc_by_code.get(c, "") for k in desc_kws)
                 and not any(e in desc_by_code.get(c, "") for e in excl)]
        total, seen = 0.0, False
        for h in heads:
            for c, v in cta.items():
                if len(c) == 6 and c.isdigit() and c.startswith(h):
                    total += v
                    seen = True
        return round(total, 2) if seen else None

    activos = leaves_sum("1")
    pasivos = leaves_sum("2")
    patrimonio = leaves_sum("3")
    reservas = None
    r21, r22 = leaves_sum("21"), leaves_sum("22")
    if r21 is not None or r22 is not None:
        reservas = round((r21 or 0) + (r22 or 0), 2)
    liq = None
    inv, efe = leaves_sum("11"), leaves_sum("12")
    if inv is not None or efe is not None:
        liq = round((inv or 0) + (efe or 0), 2)

    # Income statement: 6-digit leaves under 4/5 sub-headers → total ingresos/gastos.
    # ⚠️ ``gastos`` es el LADO DEUDOR BRUTO de la sección 5, no "gastos" en sentido
    # económico: incluye siniestros, prima cedida al reasegurador y movimientos de
    # reservas. No usarlo como numerador de un expense ratio (ver ``gastos_operativos``).
    ingresos = leaves_sum("4", ndig=6)
    gastos = leaves_sum("5", ndig=6)
    primas = children_sum_where("PRIMAS SUSCRITAS")
    siniestros = children_sum_where("RECLAMACIONES PAGADAS POR SINIESTRO")

    # Gasto operativo del SEGURO DIRECTO (51xx personas + 53xx generales), por selección
    # explícita de cuentas: comisiones de adquisición + gastos generales y administrativos
    # + otros gastos de operación. Excluye 5501 (gastos financieros: resultado financiero,
    # no técnico) y todo el reaseguro aceptado (52xx/54xx), cuyas primas no están en el
    # denominador. Mutuamente excluyente con ``siniestros`` por construcción.
    _com = heads_sum(("51", "53"), "COMISIONES A INTERMEDIARIOS")
    _ga = heads_sum(("51", "53"), "GASTOS GENERALES Y ADMINISTRATIVOS")
    _otros = heads_sum(("55",), "OTROS GASTOS DE OPERACIONES")
    gastos_operativos = (round(sum(x for x in (_com, _ga, _otros) if x is not None), 2)
                         if any(x is not None for x in (_com, _ga, _otros)) else None)

    # Reaseguro (insumo de la dimensión de Resiliencia, spec §5.5): prima cedida y
    # siniestros recuperables a cargo de reaseguradores, ambos del seguro directo.
    primas_cedidas = heads_sum(("51", "53"), "PRIMAS DE REASEG", "CEDID")
    recuperables = heads_sum(("41", "43"), "RECLAMAC", "A CARGO DE REASEG")

    # ── Base DEVENGADA / INCURRIDA ────────────────────────────────────────────────
    # La reserva se CONSTITUYE en la sección 5 (present ejercicio) y se LIBERA en la 4
    # (ejercicio anterior). Sin las dos mitades el ratio quedaba pagado-sobre-suscrito:
    # numerador y denominador en distinta base. Se excluye lo "A CARGO DE REASEGURADORES"
    # para que la medida siga siendo BRUTA en ambos lados.
    _rc_const = heads_sum(("51", "53"), "RIESGOS EN CURSO", "PRESENTE", excl=("REASEG",))
    _rc_lib = heads_sum(("41", "43"), "RIESGOS EN CURSO", "ANTERIOR", excl=("REASEG",))
    primas_devengadas = (
        round(primas + (_rc_lib or 0.0) - (_rc_const or 0.0), 2) if primas is not None else None)

    otras_prestaciones = heads_sum(("51", "53"), "OTRAS PRESTACIONES PAGADAS")
    _esp_const = heads_sum(("51", "53"), "RESERVAS ESPECIFICAS", "PRESENTE", excl=("REASEG",))
    _esp_lib = heads_sum(("41", "43"), "RESERVAS ESPECIFICAS", "ANTERIOR", excl=("REASEG",))
    _catastrof = heads_sum(("51", "53"), "CATASTROFICOS")
    salvamentos = heads_sum(("41", "43"), "SALVAMENTOS")
    siniestros_incurridos = (
        round(siniestros + (otras_prestaciones or 0.0) + (_esp_const or 0.0)
              + (_catastrof or 0.0) - (_esp_lib or 0.0) - (salvamentos or 0.0), 2)
        if siniestros is not None else None)

    def leaf(code: str) -> Optional[float]:
        return cta.get(code)

    def suma(codes) -> Optional[float]:
        vals = [cta[c] for c in codes if c in cta]
        return round(sum(vals), 2) if vals else None

    # Desglose por ramo (§5.6). El catálogo lo trae; el extractor lo colapsaba al total.
    por_ramo: Dict[str, Dict[str, Optional[float]]] = {}
    for sufijo, ramo in RAMOS_GENERALES.items():
        p, s = leaf(f"4301{sufijo}"), leaf(f"5301{sufijo}")
        if p is not None or s is not None:
            por_ramo[ramo] = {"primas": p, "siniestros": s}
    for ramo, (suf_primas, suf_sin) in RAMOS_PERSONAS.items():
        p = suma([f"4101{x}" for x in suf_primas])
        s = leaf(f"5101{suf_sin}") if suf_sin else None
        if p is not None or s is not None:
            por_ramo[ramo] = {"primas": p, "siniestros": s}

    reconciled = bool(
        activos and pasivos is not None and patrimonio is not None
        and abs(activos - pasivos - patrimonio) / activos < 0.01
    )
    if not reconciled:
        logger.warning("Balance no cuadra para '%s' (%s): A=%s P=%s Pat=%s",
                       name, period, activos, pasivos, patrimonio)

    return InsurerFinancials(
        name=name.strip(), slug=slugify_insurer(name), period=period,
        activos=activos, pasivos=pasivos, patrimonio=patrimonio,
        reservas_tecnicas=reservas, activos_liquidos=liq,
        primas=primas, siniestros=siniestros, ingresos=ingresos, gastos=gastos,
        gastos_operativos=gastos_operativos, primas_cedidas=primas_cedidas,
        recuperables_reaseguro=recuperables,
        primas_devengadas=primas_devengadas, siniestros_incurridos=siniestros_incurridos,
        otras_prestaciones=otras_prestaciones, salvamentos=salvamentos,
        por_ramo=por_ramo, reconciled=reconciled)


def extract_audited_workbook(content: bytes, period: str) -> List[InsurerFinancials]:
    """Extract every insurer sheet from an audited-statements workbook (bytes)."""
    import pandas as pd

    xl = pd.ExcelFile(io.BytesIO(content))
    out: List[InsurerFinancials] = []
    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet, header=None)
            if df.shape[1] < 3:
                continue  # index/cover sheet, not a 3-column statement
            rows = [(r[0], r[1], r[2]) for r in df.itertuples(index=False, name=None)]
            fin = _extract_sheet(rows, sheet, period)
        except Exception as e:  # noqa: BLE001 — one bad sheet never sinks the workbook
            logger.warning("Hoja '%s' no extraída: %s", sheet, e)
            fin = None
        if fin is not None:
            out.append(fin)
    return out


def to_dict(fins: List[InsurerFinancials]) -> List[Dict]:
    return [asdict(f) for f in fins]
