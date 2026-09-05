"""El costo de capital: tres términos, en pesos, y siempre un rango.

Lo que este archivo fija, y de dónde salió cada cosa:

* **No hay término de riesgo país.** La moneda funcional es RD$ (decisión del dueño), y una
  tasa libre de riesgo en pesos ya lleva adentro el riesgo país y la inflación esperada del
  peso. Sumar el CRP encima lo cuenta dos veces, infla `Ke` unos 200-400 pb y **subvalúa
  sistemáticamente a todas las entidades**. Hay test estructural de que no reaparezca.
* **La beta no se desapalanca.** Hamada supone deuda-como-financiamiento y un apalancamiento
  óptimo separable de la operación; en un banco los depósitos son materia prima y esa premisa
  es falsa. Desapalancar produciría un número con apariencia de rigor y sin significado.
* **Un cero de la curva NO es una tasa.** El cuadro anota 0 cuando el plazo no se subastó ese
  mes —35 de las 146 observaciones del plazo largo, todas con monto en blanco—. Tomarlos como
  tasas hunde la `Rf` y, si el cero es reciente, la pone en cero.
* **`Ke` es un rango.** Y si el spread cambia de signo dentro de él, ESO es el hallazgo.
* **El cruce de monedas es un error SILENCIOSO**: `Ke` y `ROE` son los dos porcentajes, la
  resta no falla, y el resultado está mal por la diferencia de inflación esperada. Se veta.
"""
import ast
import pathlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.models.models import MacroSeries
from modules.valuation.engine import cost_of_capital as cc
from shared.database.base import Base

_FUENTE = pathlib.Path(cc.__file__)


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _sembrar(db, valores, serie=cc.SERIE_RF):
    """`valores` = lista de (período, tasa en %)."""
    for p, v in valores:
        db.add(MacroSeries(series_code=serie, period=p, value=v))
    db.commit()


#: La curva real de 2025-2026, con los ceros que el cuadro trae cuando no hubo subasta.
_CURVA_REAL = [("2025-01", 11.96), ("2025-04", 9.71), ("2025-07", 9.61), ("2025-10", 9.93),
               ("2026-01", 9.94), ("2026-03", 9.61), ("2026-05", 10.02), ("2026-07", 9.78)]


# ── los tres términos ───────────────────────────────────────────────────────────────


def test_NO_hay_termino_de_riesgo_pais(db):
    _sembrar(db, _CURVA_REAL)
    ke = cc.calcular(db)
    nombres = " ".join(t.nombre.lower() for t in ke.terminos)
    assert "riesgo pais" not in nombres and "crp" not in nombres
    assert len(ke.terminos) == 2, "la descomposición debería tener Rf y β×ERP, nada más"


def test_el_codigo_DECLARA_por_que_no_hay_CRP():
    """La ausencia de un término es invisible: sin el motivo escrito, el próximo lector lo
    agrega creyendo que fue un olvido."""
    fuente = _FUENTE.read_text()
    assert "dos veces" in fuente and "riesgo país" in fuente


def test_la_beta_NO_se_desapalanca():
    """Guard estructural: si aparece Hamada o un desapalancamiento, el supuesto falso volvió."""
    fuente = _FUENTE.read_text().lower()
    for prohibido in ("hamada(", "unlever", "desapalancar(", "beta_desapalancada"):
        assert prohibido not in fuente, f"apareció «{prohibido}»: la beta se desapalancó"
    assert "materia prima" in fuente, "no está escrito POR QUÉ no se desapalanca"


def test_beta_y_erp_viajan_como_RUBRICA(db):
    _sembrar(db, _CURVA_REAL)
    ke = cc.calcular(db)
    prima = next(t for t in ke.terminos if "β" in t.nombre)
    assert prima.es_rubrica, "β×ERP se declaró como dato real"
    rf = next(t for t in ke.terminos if "Rf" in t.nombre)
    assert not rf.es_rubrica, "la Rf es dato observado, no rúbrica"
    assert 0.0 < ke.fraccion_de_rubrica < 1.0


# ── el cero que no es una tasa ──────────────────────────────────────────────────────


def test_un_cero_de_la_curva_no_entra_como_tasa(db):
    """35 de las 146 observaciones del plazo largo son ceros con el monto en blanco: no hubo
    subasta. Si entran, hunden la Rf."""
    _sembrar(db, _CURVA_REAL + [("2026-08", 0.0)])
    bajo, alto, n, avisos = cc.rf_de_la_curva(db)
    assert bajo > 5.0, f"un cero se coló en la Rf: bajo={bajo}"
    assert any("cero" in a for a in avisos), "descartó el cero sin declararlo"


def test_descartar_ceros_se_DECLARA_y_no_se_hace_en_silencio(db):
    _sembrar(db, _CURVA_REAL + [("2026-08", 0.0), ("2026-09", 0.0)])
    _b, _a, _n, avisos = cc.rf_de_la_curva(db)
    assert avisos and "2" in avisos[0]


# ── el rango ────────────────────────────────────────────────────────────────────────


def test_ke_es_un_RANGO_y_no_un_punto(db):
    _sembrar(db, _CURVA_REAL)
    ke = cc.calcular(db)
    assert ke.alto > ke.bajo
    assert ke.amplitud > 1.0, "un rango de menos de 100 pb no transporta la incertidumbre real"


def test_el_punto_medio_esta_NOMBRADO_como_lo_que_es(db):
    """Existe para graficar. Que la clave lo diga es la diferencia entre un gráfico y una
    cifra que alguien cita como «el» costo de capital."""
    _sembrar(db, _CURVA_REAL)
    d = cc.a_dict(cc.calcular(db))
    assert "punto_medio_solo_para_graficar" in d
    assert "ke" not in d or isinstance(d.get("rango"), list)


def test_la_sensibilidad_va_en_pasos_de_50pb_y_cubre_los_DOS_extremos(db):
    _sembrar(db, _CURVA_REAL)
    ke = cc.calcular(db)
    valores = [k for k, _e in ke.sensibilidad]
    assert valores[0] == pytest.approx(ke.bajo, abs=1e-6)
    assert valores[-1] == pytest.approx(ke.alto, abs=1e-6)
    saltos = [round(b - a, 4) for a, b in zip(valores, valores[1:])]
    assert all(s <= cc.PASO_SENSIBILIDAD + 1e-9 for s in saltos), f"pasos: {saltos}"
    etiquetas = [e for _k, e in ke.sensibilidad]
    assert "extremo favorable" in etiquetas and "extremo adverso" in etiquetas


# ── el hallazgo ─────────────────────────────────────────────────────────────────────


def test_el_cambio_de_signo_se_DETECTA(db):
    """Un ROE que cae DENTRO del rango de Ke no tiene respuesta única, y ése es el hallazgo."""
    _sembrar(db, _CURVA_REAL)
    ke = cc.calcular(db)
    adentro = (ke.bajo + ke.alto) / 2.0
    assert cc.cambia_de_signo(ke, adentro, moneda_roe="DOP")


def test_un_ROE_claramente_fuera_del_rango_NO_cambia_de_signo(db):
    """El contraejemplo: sin él, un detector que devolviera siempre True pasaría el de arriba."""
    _sembrar(db, _CURVA_REAL)
    ke = cc.calcular(db)
    assert not cc.cambia_de_signo(ke, ke.alto + 5.0, moneda_roe="DOP")
    assert not cc.cambia_de_signo(ke, ke.bajo - 5.0, moneda_roe="DOP")


# ── el cruce de monedas ─────────────────────────────────────────────────────────────


def test_restar_un_ROE_en_otra_moneda_LANZA(db):
    """El sensor de T-VL-3. Sin él el error es silencioso: los dos son porcentajes."""
    _sembrar(db, _CURVA_REAL)
    ke = cc.calcular(db)
    with pytest.raises(cc.MonedaCruzadaError):
        cc.spread(ke, 13.2, moneda_roe="USD")
    with pytest.raises(cc.MonedaCruzadaError):
        cc.cambia_de_signo(ke, 13.2, moneda_roe="USD")


def test_en_la_misma_moneda_el_spread_se_calcula(db):
    """Contraejemplo del anterior: un guard que lanzara siempre pasaría el test de arriba."""
    _sembrar(db, _CURVA_REAL)
    ke = cc.calcular(db)
    assert cc.spread(ke, ke.punto_medio + 2.0, moneda_roe="DOP") == pytest.approx(2.0)


def test_la_moneda_del_motor_es_una_CONSTANTE():
    """Si vive en un literal repartido por el código, una mitad se cambia y la otra no."""
    arbol = ast.parse(_FUENTE.read_text())
    asignada = any(isinstance(n, ast.Assign)
                   and any(getattr(t, "id", "") == "MONEDA" for t in n.targets)
                   for n in arbol.body)
    assert asignada and cc.MONEDA == "DOP"
