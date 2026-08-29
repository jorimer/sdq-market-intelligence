"""La banda de Resiliencia nunca se publica sin el número que la produce.

De dónde salió. Una revisión externa de dos informes reales concluyó que nuestros umbrales
de banda eran arbitrarios: veía 60,06 rotulado «En vigilancia» y 59,73 «Adecuada» en la
misma tabla. Los umbrales estaban bien y son constantes. Lo que fallaba es que la tabla
ponía la columna «Score» —el score GLOBAL— al lado de «Banda», que sale del eje de
RESILIENCIA: otro número, que reagrega solidez, calidad, liquidez y diversificación y
EXCLUYE eficiencia. La cifra que explicaba la banda no se publicaba en ninguna parte, así
que el lector no tenía cómo verificarla y concluyó lo único que podía concluir.

Es la doctrina del sujeto que viaja con el número, aplicada a una banda: publicar una
clasificación sin su magnitud la vuelve imposible de auditar. Y el defecto era de CLASE —
aparecía en seis payloads y tres tablas del PDF a la vez—, así que la cura es estructural.
"""

import ast
import pathlib

import pytest

from modules.banking_score.products_year_review import SAMPLE_REVISION
from modules.banking_score.scoring.perfil_sdq import banda_resiliencia

_REPORTES = sorted(pathlib.Path("modules/banking_score/reports").glob("*.py"))
# Acompañantes válidos: la magnitud del eje, en cualquiera de las formas en que un payload
# la nombra según sea una fila, un extremo o un tramo.
_ACOMPANA = {"resiliencia", "resiliencia_hasta", "resiliencia_desde", "resiliencia_anterior"}


def _dicts_con_banda(fuente: str):
    for nodo in ast.walk(ast.parse(fuente)):
        if not isinstance(nodo, ast.Dict):
            continue
        claves = {k.value for k in nodo.keys
                  if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        # Solo claves que nombran una BANDA. `desde`/`hasta` a secas también rotulan años y
        # cortes: dispararían con la tendencia plurianual, que no publica ninguna banda.
        if {c for c in claves if c == "banda" or c.startswith("banda_")} and not claves & _ACOMPANA:
            yield nodo.lineno, sorted(claves)


def test_el_barrido_encuentra_algo():
    """Una aserción de ausencia pasa sola: si el glob se rompe, el test de abajo aprueba un
    repo vacío. Esto comprueba que hay dónde mirar."""
    assert len(_REPORTES) >= 5, f"el glob de informes encontró {len(_REPORTES)} archivos"
    assert any("banda" in f.read_text() for f in _REPORTES)


@pytest.mark.parametrize("archivo", _REPORTES, ids=lambda f: f.name)
def test_ninguna_banda_se_publica_sin_su_resiliencia(archivo):
    huerfanos = list(_dicts_con_banda(archivo.read_text()))
    assert not huerfanos, (
        f"{archivo.name}: publica una banda sin el score de Resiliencia que la produce, en "
        f"{[(ln, cl) for ln, cl in huerfanos]}. La banda NO sale del score global; sin su "
        f"magnitud al lado el lector no puede verificarla.")


def test_la_muestra_curada_reproduce_sus_propias_bandas():
    """Si la muestra no fuera coherente consigo misma, enseñaría el defecto que arreglamos."""
    filas = (list(SAMPLE_REVISION["serie"])
             + [SAMPLE_REVISION["apertura"], SAMPLE_REVISION["cierre"]])
    for f in filas:
        assert f.get("resiliencia") is not None, f"la muestra omite la resiliencia en {f}"
        assert banda_resiliencia(f["resiliencia"]) == f["banda"], (
            f"la muestra dice «{f['banda']}» para resiliencia {f['resiliencia']}, pero la "
            f"regla da «{banda_resiliencia(f['resiliencia'])}»")
