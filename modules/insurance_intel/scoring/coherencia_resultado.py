"""¿El combined ratio coincide con lo que dice el estado de resultados? (oráculo externo).

**Por qué existe.** El combined ratio se arma con cuentas SELECCIONADAS de las secciones 4 y
5 del catálogo SIS. Si la selección está mal —una cuenta de más, una de menos, un lado bruto
contra otro neto— el ratio queda equivocado y no hay nada dentro de su propio cómputo que lo
delate: los cuatro defectos de construcción que encontró la revisión actuarial de 2026-08
convivieron con 3.255 tests en verde.

La misma acta auditada trae dos líneas que el ratio NO usa y que tienen que ser coherentes
con él: el **resultado del ejercicio** (sección 4 menos sección 5, el estado completo) y la
**trayectoria del patrimonio**. Nadie pierde 40 centavos por peso de prima durante cinco
ejercicios y crece el patrimonio 17% anual. Cruzarlos convierte una revisión externa —que
depende de que un tercero mire y tenga tiempo— en una condición que corre sola.

**Qué NO es.** No es una segunda medición del desempeño ni ajusta ningún score. Es un
detector de INCOHERENCIA: dice "estas dos lecturas de la misma acta no pueden ser ambas
ciertas", y deja la explicación al analista. Sobre el panel 2018-2024 marcó tres compañías
—Angloamericana, Worldwide y Seguros Crecer— y las tres resultaron tener una razón
estructural (cesión extrema, negocio de anualidades), no un error de extracción. Las de
combined alto por deterioro REAL —Unit con margen de −330%, Multiseguros con el patrimonio
cayendo 60% anual— no las marca, que es la prueba de que discrimina.
"""
from typing import Any, Dict, List, Optional

# Umbral de contradicción. Un combined por encima de este nivel afirma una pérdida de
# suscripción grande; si aun así el resultado del ejercicio es POSITIVO, las dos lecturas no
# cierran. Se elige alto a propósito: entre 100% y 110% la diferencia la explica sin drama el
# resultado financiero de cualquier compañía, y marcar ahí sería ruido.
CR_CONTRADICTORIO = 1.15

# Margen neto (resultado del ejercicio / prima devengada) por encima del cual el resultado
# NO admite la pérdida técnica que el combined afirma. Cero sería el corte natural, pero un
# margen apenas positivo puede salir de un resultado financiero legítimo; se exige que la
# compañía sea claramente rentable para llamar a la contradicción.
MARGEN_CONTRADICTORIO = 0.05


def _cagr(serie: List[tuple]) -> Optional[float]:
    """CAGR del patrimonio sobre ``[(año, valor)]`` ordenado. None si no es computable."""
    vivos = [(a, v) for a, v in sorted(serie) if v is not None and v > 0]
    if len(vivos) < 3:
        return None
    return (vivos[-1][1] / vivos[0][1]) ** (1.0 / (len(vivos) - 1)) - 1.0


def evaluar(slug: str, combined: Optional[float],
            ejercicios: Dict[str, Dict[str, Optional[float]]]) -> Optional[Dict[str, Any]]:
    """``None`` si es coherente; el hallazgo si el combined contradice el estado de resultados.

    *ejercicios* es ``{año: {ingresos_totales, gastos_totales, primas_devengadas, patrimonio}}``
    tal como viene de ``insurance_series`` — las cuatro son líneas que el combined no usa.

    >>> ej = {"2022": {"ingresos_totales": 300.0, "gastos_totales": 200.0,
    ...                "primas_devengadas": 100.0, "patrimonio": 100.0},
    ...       "2023": {"ingresos_totales": 300.0, "gastos_totales": 200.0,
    ...                "primas_devengadas": 100.0, "patrimonio": 130.0},
    ...       "2024": {"ingresos_totales": 300.0, "gastos_totales": 200.0,
    ...                "primas_devengadas": 100.0, "patrimonio": 170.0}}
    >>> evaluar("x", 1.40, ej)["margen_neto"]
    1.0
    >>> evaluar("x", 0.85, ej) is None      # combined sano: nada que contradecir
    True
    """
    if combined is None or combined <= CR_CONTRADICTORIO:
        return None

    resultado = prima = 0.0
    patrimonio: List[tuple] = []
    for año, s in sorted(ejercicios.items()):
        ing, gas = s.get("ingresos_totales"), s.get("gastos_totales")
        pd_ = s.get("primas_devengadas")
        if s.get("patrimonio") is not None:
            patrimonio.append((año, s["patrimonio"]))
        if ing is None or gas is None or not pd_:
            continue
        resultado += ing - gas
        prima += pd_
    if prima <= 0:
        # Sin base no se afirma contradicción: la ausencia de dato NO es un hallazgo.
        return None

    margen = resultado / prima
    if margen <= MARGEN_CONTRADICTORIO:
        return None  # el resultado ACOMPAÑA al combined: coherente, aunque sea malo

    return {
        "slug": slug,
        "combined": round(combined, 4),
        "margen_neto": round(margen, 4),
        "patrimonio_cagr": (round(c, 4) if (c := _cagr(patrimonio)) is not None else None),
        "detalle": (
            f"el combined de {combined * 100:.0f}% afirma una pérdida de suscripción de "
            f"{(combined - 1) * 100:.0f} puntos, pero el estado de resultados da un margen "
            f"neto de {margen * 100:+.0f}% sobre la prima devengada"),
    }


def revisar_panel(db) -> Dict[str, Any]:
    """Corre el cruce sobre todo el panel. Devuelve los hallazgos, sin tocar ningún score."""
    from modules.insurance_intel.models.models import InsuranceEntity, InsuranceSeries
    from modules.insurance_intel.scoring.isf import _canon_map, _official_index
    from modules.insurance_intel.scoring.perfil_sdq import (
        metricas_del_ciclo, motivo_no_publicable, panel_por_aseguradora,
    )

    # Mismo mapa canónico que el resto del módulo: leer `insurance_series` por el slug
    # derivado devuelve cero filas para las siete aseguradoras cuyo nombre de hoja se trunca
    # a 31 caracteres (regla estructural en `test_regla_canon`).
    ents = (db.query(InsuranceEntity)
            .filter(InsuranceEntity.entity_type == "aseguradora").all())
    canon, _ = _canon_map(ents, _official_index())
    rows = (db.query(InsuranceSeries)
            .filter(InsuranceSeries.entity_slug.in_(list(canon) or [""]),
                    InsuranceSeries.dimension.is_(None),
                    InsuranceSeries.value.isnot(None)).all())
    por: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
    for r in rows:
        c = canon.get(r.entity_slug)
        if c is not None:
            por.setdefault(c[2], {}).setdefault(r.period, {})[r.series_code] = r.value

    hallazgos: List[Dict[str, Any]] = []
    explicados: List[Dict[str, Any]] = []
    for slug, info in panel_por_aseguradora(db).items():
        ciclo = metricas_del_ciclo(info["ejercicios"])
        if not ciclo:
            continue
        h = evaluar(slug, ciclo["combined_promedio"], por.get(slug) or {})
        if h is None:
            continue
        # Una contradicción que la compuerta de §5.2 ya explica no es un hallazgo abierto:
        # el eje no se publica y el motivo está declarado. Se cuenta aparte para que el
        # día que la compuerta deje de cubrirla, reaparezca como hallazgo.
        motivo = motivo_no_publicable(ciclo)
        (explicados if motivo else hallazgos).append({**h, "motivo_declarado": motivo})

    return {"hallazgos": hallazgos, "explicados": explicados,
            "total_evaluadas": len(por)}
