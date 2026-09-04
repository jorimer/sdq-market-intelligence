"""Cuando bajo cada año hay CONCEPTOS, son series distintas — no un período repetido.

La posición de inversión internacional publica, para cada año, seis columnas: `Saldo al
inicio | Transacciones Netas | Variaciones de Tipo de Cambio | Variaciones de Precios |
Otras Variaciones | Saldo al final`. Es la reconciliación entre el stock de apertura y el de
cierre — seis magnitudes distintas, no seis veces la misma.

El motor solo sabía leer un sub-encabezado si era un PERÍODO (trimestre o mes). Con conceptos
no lo miraba, así que las seis columnas de un año caían en el mismo `(serie, año)` y el
dedupe «último gana» dejaba una arbitraria: `activos` en 2009 tenía cinco valores distintos
—10.959,6 · −426,7 · −32,7 · 5,8 · 0,0— de los que sobrevivía uno. 2.970 valores en conflicto
en `piianual_6` y 1.855 en `piianual`.

Bien leído, el archivo no pierde nada: multiplica por seis su información real.
"""
from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.inference import infer_spec
from shared.data.bcrd_excel.workbook import Grid, Workbook

_CONCEPTOS = ["Saldo al inicio", "Transacciones Netas", "Variaciones de Precios",
              "Otras Variaciones", "Saldo al final"]


def _hoja(anios=(2010, 2011, 2012, 2013, 2014, 2015)):
    ancho = 1 + len(anios) * len(_CONCEPTOS)
    fila_anios = [None] * ancho
    fila_conc = [None] * ancho
    c = 1
    for a in anios:
        fila_anios[c] = a
        for k in _CONCEPTOS:
            fila_conc[c] = k
            c += 1
    filas = [["POSICION DE INVERSION"], [], fila_anios, fila_conc]
    v = 100.0
    for etiqueta in ("I. Activos", "II. Pasivos"):
        fila = [etiqueta] + [None] * (ancho - 1)
        for i in range(1, ancho):
            fila[i] = v
            v += 1
        filas.append(fila)
    return Workbook(path=None, grids=[Grid(name="PII", rows=filas)])


def _recs():
    wb = _hoja()
    sp = infer_spec(wb, "piianual_6.xlsx")
    sp.code_prefix = "p"
    return sp, extract_records(wb, sp)


def test_el_concepto_se_reconoce_como_dimension():
    sp, _ = _recs()
    assert sp.dimension_header_row == 3, f"dimension_header_row={sp.dimension_header_row}"


def test_cada_concepto_es_su_propia_serie():
    _, recs = _recs()
    activos = {r.series for r in recs if ".activos" in r.series}
    assert len(activos) == len(_CONCEPTOS), sorted(activos)
    assert any(c.endswith(".transacciones_netas") for c in activos), sorted(activos)
    assert any(c.endswith(".saldo_al_final") for c in activos), sorted(activos)


def test_ya_no_colapsan_en_el_ano():
    _, recs = _recs()
    vistos = {}
    for r in recs:
        k = (r.series, r.period)
        assert k not in vistos, f"{k} aparece dos veces: siguen colapsando"
        vistos[k] = r.value


def test_el_ano_de_cada_columna_es_el_de_SU_bloque():
    _, recs = _recs()
    d = {(r.series.split(".")[-1], r.period): r.value for r in recs if ".activos" in r.series}
    # el primer bloque es 2010: sus cinco conceptos tienen que estar en 2010, no en 2009
    assert ("transacciones_netas", "2010") in d
    assert ("transacciones_netas", "2009") not in d
