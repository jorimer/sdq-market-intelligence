"""La naturaleza de las series de SEGUROS que entran al feed mensual (Fase 3 del plan).

La naturaleza elige la línea base del delta (`shared/observations/delta.py`): un stock contra su
último nivel, un flujo contra el mismo mes del año anterior y con ventana móvil de doce meses.
Equivocarla no da un error: da una cifra publicable y falsa.

* La afiliación SFS son personas cubiertas a una fecha: un STOCK. Sin declarar salía `unknown`
  y la sección no la computaba.
* Los agregados de sistema de las ARS son cuentas de balance: STOCK.
* Los ingresos, gastos y el beneficio de las ARS son ACUMULADOS AL MES. No son `flow`: la
  ventana móvil sumaría acumulados. Y sin declarar SÍ salen `flow`, porque la unidad «RD$»
  decide antes que nada. Por eso se declaran `unknown` explícitamente.
"""
import json
import pathlib

import pytest

from shared.data.series_nature import DECLARED, FLOW, STOCK, UNKNOWN, infer_nature

FIXTURE_ARS = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sisalril_ars.json"


@pytest.mark.parametrize("codigo", [
    "sfs.afiliacion.total", "sfs.afiliacion.contributivo", "sfs.afiliacion.subsidiado",
])
def test_la_afiliacion_SFS_es_un_STOCK(codigo):
    """Con la unidad que emite el conector («personas»), no con una inventada."""
    assert infer_nature("personas", code=codigo) == STOCK


@pytest.mark.parametrize("codigo", [
    "ars.sistema.patrimonio", "ars.sistema.activo_total",
    "ars.sistema.margen_inversiones", "ars.sistema.margen_requerido",
])
def test_los_agregados_de_sistema_de_las_ARS_son_STOCK(codigo):
    assert infer_nature("RD$", code=codigo) == STOCK


@pytest.mark.parametrize("codigo", ["ars.ingreso_salud", "ars.gasto_salud", "ars.beneficio_neto"])
def test_un_ACUMULADO_AL_MES_no_sale_flujo(codigo):
    """Sin la declaración, «RD$» los haría `flow` y la ventana móvil sumaría acumulados."""
    assert infer_nature("RD$", code=codigo) == UNKNOWN


def test_la_declaracion_de_los_acumulados_es_NECESARIA():
    """Contrapeso: prueba que sin la entrada en `DECLARED` la inferencia SÍ los hace flujo.

    Si un día la unidad dejara de decidir, este test avisa que la declaración sobra — en vez de
    que la de arriba pase sin estar protegiendo nada.
    """
    sin_declarar = "ars.ingreso_salud_de_prueba_sin_declarar"
    assert sin_declarar not in DECLARED
    assert infer_nature("RD$", code=sin_declarar) == FLOW


def test_el_fixture_REAL_muestra_que_esas_series_acumulan_dentro_del_anio():
    """La razón de la declaración, leída del dato del emisor y no de un comentario.

    En cada ARS del fixture, de un mes al siguiente del mismo año, el ingreso en salud no baja:
    así se ve un acumulado. Si el emisor cambiara a cifras mensuales sueltas, esto falla y la
    declaración `unknown` hay que revisarla.
    """
    fx = json.loads(FIXTURE_ARS.read_text(encoding="utf-8"))
    pares_revisados, bajadas = 0, []
    for ars_id, rec in (fx.get("entities") or {}).items():
        serie = ((rec.get("series") or {}).get("ingreso_salud") or {})
        obs = serie.get("observations", serie) if isinstance(serie, dict) else {}
        puntos = sorted((p, v) for p, v in obs.items() if v is not None)
        for (p0, v0), (p1, v1) in zip(puntos, puntos[1:]):
            if p0[:4] != p1[:4]:
                continue
            pares_revisados += 1
            if v1 < v0:
                bajadas.append((ars_id, p0, p1))
    assert pares_revisados >= 10, f"el fixture casi no tiene meses consecutivos: {pares_revisados}"
    assert not bajadas, f"el ingreso en salud BAJA dentro del año, no es acumulado: {bajadas[:5]}"


def test_las_claves_se_declaran_COMPLETAS_y_no_por_la_hoja():
    """«total» o «patrimonio» sueltos atraparían series de otros ejes."""
    for hoja in ("total", "contributivo", "subsidiado", "patrimonio", "activo_total",
                 "ingreso_salud", "gasto_salud", "beneficio_neto"):
        assert hoja not in DECLARED, f"«{hoja}» declarado como hoja suelta"
