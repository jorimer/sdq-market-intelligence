"""La desagregación sectorial: la restricción de agregación y lo que la sostiene.

Lo que este archivo fija, y por qué cada cosa:

* **La reconciliación es exacta, y el reparto es por PESO.** Repartir la brecha proporcional
  al crecimiento proyectado le pega más al que más se mueve y puede darle vuelta el signo a
  un sector — justo la lectura que la sección existe para dar. Con reparto por peso el ajuste
  en pp es el mismo para todos y el orden se conserva. Hay un test que lo distingue.
* **La partición se comprueba en el dato.** Que las 17 actividades más los impuestos sumen el
  PIB es un hecho empírico sobre la fuente, no un teorema. Si el BCRD reorganiza el cuadro,
  la restricción se queda sin sustrato y hay que enterarse acá.
* **Un sector con hueco se DECLARA, no se rellena.**
* **`elegir_lambda` no mira el futuro.** El test le cambia el futuro al panel y exige que la
  elección no se mueva.
* **Las 18×2 series declaradas tienen que existir.** Ocho de los códigos dependen de una
  partición del spec interpretado; si una reinterpretación las mueve, la sección perdería
  cinco actividades EN SILENCIO. Éste es el modo de falla caro y ésta es su alarma.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import backtest_sectorial as B
from modules.macro_monitor.forecasting import sectoral as S
from modules.macro_monitor.models.models import MacroSeries
from shared.database.base import Base

TRIMESTRES = [f"{a}-Q{q}" for a in range(2018, 2027) for q in (1, 2, 3, 4)][:33]


def _sembrar(db, saltear=(), huecos=()):
    """Un cuadro sintético que CUMPLE la partición: el PIB se construye sumando las partes.

    Deliberado: si el fixture partiera de un PIB inventado y le colgara partes, el test de
    partición pasaría o fallaría por el azar del redondeo en vez de por el código.
    """
    pesos = {c.clave: 1.0 + i for i, c in enumerate(S.COMPONENTES)}
    for i, t in enumerate(TRIMESTRES):
        total_nom = 0.0
        total_vol = 0.0
        for j, c in enumerate(S.COMPONENTES):
            if c.clave in saltear:
                continue
            nom = pesos[c.clave] * 1000 * (1.02 ** i)
            vol = 100 * (1.0 + 0.004 * (j % 5)) ** i
            if not (c.clave in huecos and i in (10, 11)):
                db.add(MacroSeries(series_code=c.nominal, period=t, value=nom))
                db.add(MacroSeries(series_code=c.volumen, period=t, value=vol))
            total_nom += nom
            total_vol += pesos[c.clave] * vol
        db.add(MacroSeries(series_code=S.PIB_NOMINAL, period=t, value=total_nom))
        db.add(MacroSeries(series_code=S.PIB_VOLUMEN, period=t,
                           value=total_vol / sum(pesos.values())))
    db.commit()


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


# --------------------------------------------------------------- la restricción


def test_la_reconciliacion_es_exacta():
    crudo = {"a": 5.0, "b": -2.0, "c": 11.0}
    pesos = {"a": 0.5, "b": 0.3, "c": 0.2}
    ajustado, brecha = S.reconciliar(crudo, pesos, g_pib=3.0,
                                     medida_del_agregado=S.MEDIDA_DEL_PANEL)
    suma = sum(pesos[k] * ajustado[k] for k in ajustado)
    assert suma == pytest.approx(3.0, abs=1e-12)
    assert brecha == pytest.approx(3.0 - sum(pesos[k] * crudo[k] for k in crudo), abs=1e-12)


def test_el_reparto_es_por_peso_y_no_por_crecimiento():
    """El ajuste en pp es IDÉNTICO para todos, y el orden entre sectores no cambia.

    Un reparto proporcional al crecimiento rompe las dos cosas: le movería 11,0 mucho más que
    a −2,0 y podría reordenarlos. Este test es el que separa un reparto del otro.
    """
    crudo = {"a": 5.0, "b": -2.0, "c": 11.0}
    pesos = {"a": 0.5, "b": 0.3, "c": 0.2}
    ajustado, _ = S.reconciliar(crudo, pesos, g_pib=3.0,
                                medida_del_agregado=S.MEDIDA_DEL_PANEL)
    ajustes = {k: ajustado[k] - crudo[k] for k in crudo}
    assert len(set(round(v, 12) for v in ajustes.values())) == 1
    assert (sorted(crudo, key=lambda k: crudo[k])
            == sorted(ajustado, key=lambda k: ajustado[k]))


def test_la_proyeccion_reconcilia_contra_el_agregado(db):
    _sembrar(db)
    pan = S.construir_panel(db)
    pr = S.proyectar(pan, g_pib=4.25, horizonte="2026-Q2",
                     origen_del_agregado="bvar_minnesota.v1",
                     medida_del_agregado=S.MEDIDA_DEL_PANEL)
    assert pr.suma_de_incidencias == pytest.approx(4.25, abs=1e-12)
    assert len(pr.sectores) == len(S.COMPONENTES)


def test_el_desglose_de_un_escenario_es_un_escenario(db):
    """La propiedad viaja con el dato. Si `es_escenario` se perdiera en el desglose, un
    horizonte sin track record se publicaría como si tuviera uno."""
    _sembrar(db)
    pan = S.construir_panel(db)
    pr = S.proyectar(pan, g_pib=3.0, horizonte="2027-Q1",
                     origen_del_agregado="bvar_minnesota.v1", es_escenario=True,
                     medida_del_agregado=S.MEDIDA_DEL_PANEL)
    assert pr.es_escenario is True


# ------------------------------------------------------------------ la partición


def test_la_particion_se_comprueba_en_el_dato(db):
    _sembrar(db)
    p = S.verificar_particion(db)
    assert p.cierra
    assert p.trimestres == len(TRIMESTRES)
    assert p.error_maximo <= S.TOLERANCIA_PARTICION


def test_si_falta_un_componente_la_particion_no_cierra(db):
    """Sin esta rama, perder una actividad se leería como «el PIB creció menos»."""
    _sembrar(db, saltear=("comercio",))
    p = S.verificar_particion(db)
    assert not p.cierra
    assert "comercio" in p.faltantes


def test_son_diecisiete_actividades_mas_impuestos():
    claves = [c.clave for c in S.COMPONENTES]
    assert len(claves) == len(set(claves)) == 18
    assert "impuestos" in claves


# ------------------------------------------------------------------ las brechas


def test_un_sector_con_hueco_no_se_proyecta(db):
    _sembrar(db, huecos=("minas",))
    pan = S.construir_panel(db)
    assert "minas" in pan.brechas
    assert "minas" not in pan.crecimiento
    assert "minas" not in pan.proyectables
    assert "hueco" in pan.brechas["minas"] or "sin dato" in pan.brechas["minas"]


def test_las_brechas_viajan_en_la_proyeccion(db):
    """Declarar la brecha en el panel y perderla en la salida es no declararla."""
    _sembrar(db, huecos=("minas",))
    pan = S.construir_panel(db)
    pr = S.proyectar(pan, g_pib=3.0, horizonte="2026-Q2", origen_del_agregado="x",
                     medida_del_agregado=S.MEDIDA_DEL_PANEL)
    assert "minas" in pr.brechas
    assert all(s.clave != "minas" for s in pr.sectores)
    # y lo que queda sigue reconciliando exacto
    assert pr.suma_de_incidencias == pytest.approx(3.0, abs=1e-12)


# ------------------------------------------------------------------ el backtest


def test_el_metodo_le_gana_a_la_proporcion_pura(db):
    _sembrar(db)
    r = B.correr(S.construir_panel(db))
    assert r.n_cortes > 0 and r.n_componentes == 18
    assert r.rmse < r.rmse_base
    assert r.publica


def test_elegir_lambda_no_mira_el_futuro(db):
    """Se le cambia el futuro al panel y la elección no se puede mover."""
    _sembrar(db)
    pan = S.construir_panel(db)
    corte = len(pan.trimestres) - 5
    antes = B.elegir_lambda(pan, corte)
    envenenado = S.PanelSectorial(
        trimestres=pan.trimestres,
        crecimiento={k: v[:corte] + tuple(x * 100 + 500 for x in v[corte:])
                     for k, v in pan.crecimiento.items()},
        pib=pan.pib[:corte] + tuple(x * 100 + 500 for x in pan.pib[corte:]),
        pesos=pan.pesos, brechas=pan.brechas,
    )
    assert B.elegir_lambda(envenenado, corte) == antes


# ------------------------------------------------- la alarma del bloque partido


def test_las_series_declaradas_existen(db):
    _sembrar(db)
    assert S.verificar_componentes(db) == {}


def test_verificar_componentes_delata_un_codigo_movido(db):
    _sembrar(db, saltear=("administracion_publica",))
    faltan = S.verificar_componentes(db)
    assert "administracion_publica.nominal" in faltan
    assert "administracion_publica.volumen" in faltan
