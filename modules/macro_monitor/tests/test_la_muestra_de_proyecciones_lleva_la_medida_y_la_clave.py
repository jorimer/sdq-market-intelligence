"""La muestra curada de proyecciones lleva la MEDIDA que el bloque emite y la CLAVE de cada fila.

Complementa `test_la_muestra_curada_cierra_sola.py` (#1154), que cubre la aritmética. Acá lo
que quedaba: las proyecciones y los escenarios de la muestra seguían rotulados `dlog_pct`
cuando el bloque emite la variación INTERANUAL desde #1117 —la vidriera enseñaba una unidad
que el producto ya no publica—, y las filas sectoriales no llevaban su clave, que es el
identificador con el que `brechas` nombra a las ausentes: muestra y payload real no tenían la
misma forma.
"""
from __future__ import annotations

from modules.macro_monitor.forecasting import bloque
from modules.macro_monitor.forecasting.sectoral import COMPONENTES
from modules.macro_monitor.products_forecast import _SAMPLE_PAYLOAD
from shared.data import medida_de_pronostico as med


def test_las_proyecciones_y_escenarios_de_la_muestra_llevan_la_MEDIDA_que_el_bloque_emite():
    esperada = {"interanual": med.YOY_PCT, "dlog": med.DLOG_PCT}[bloque.medida_de("pib_real")]
    filas = list(_SAMPLE_PAYLOAD["proyecciones"]) + list(_SAMPLE_PAYLOAD.get("escenarios") or [])
    assert filas
    for d in filas:
        assert d["medida"] == esperada, (
            f"{d['horizonte']}: la muestra rotula {d['medida']} y el bloque emite {esperada}")


def test_cada_fila_sectorial_lleva_su_CLAVE_y_entre_filas_y_brechas_esta_el_cuadro_entero():
    s = _SAMPLE_PAYLOAD["sectorial"]
    etiquetas = {c.clave: c.etiqueta for c in COMPONENTES}
    for f in s["sectores"]:
        assert f.get("clave") in etiquetas, f"fila sin clave válida: {f.get('etiqueta')}"
        assert f["etiqueta"] == etiquetas[f["clave"]], f["clave"]
    presentes = {f["clave"] for f in s["sectores"]} | set(s["brechas"])
    assert presentes == set(etiquetas), sorted(set(etiquetas) ^ presentes)


def test_la_cifra_determinada_de_la_muestra_trae_su_interanual():
    c = _SAMPLE_PAYLOAD["cifra_determinada"]
    assert c.get("interanual_pct") is not None and c["interanual_pct"] != c["dlog_pct"]
