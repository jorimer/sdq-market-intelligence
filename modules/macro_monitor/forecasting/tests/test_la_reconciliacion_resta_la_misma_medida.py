"""La reconciliación sectorial restaba una tasa ANUAL de una tasa TRIMESTRAL.

El defecto, medido en el informe publicado el 2026-09-05: la tabla sectorial mostraba **8 de
18 actividades contrayéndose** cuando el modelo crudo proyectaba las 18 positivas. Las ocho
contracciones eran el residuo de una resta entre unidades distintas.

* el panel sectorial mide **interanual** — `_interanual`, contra `trimestres[i-4]`;
* el BVAR medía **trimestral** — `DLOG` entre trimestres consecutivos;
* `products_forecast` pasaba el punto del BVAR a `reconciliar`, que lo restaba de una suma
  ponderada de crecimientos interanuales.

Sobre la serie real de producción (77 trimestres, 2007-Q1 → 2026-Q1) el QoQ promedia +1,13 %
y el YoY +4,54 %: una diferencia sistemática de 3,41 pp. La brecha publicada fue −3,536 pp.
No era desacuerdo entre modelos; era la diferencia entre una tasa anual y una trimestral.

Y había un segundo defecto encima: el QoQ se hacía sobre la serie **original**, sin
desestacionalizar. El QoQ medio por trimestre del año iba de −1,13 % (Q3) a +4,67 % (Q4) —
5,80 pp de amplitud puramente de calendario, así que el titular del informe dependía de en
qué trimestre caía el horizonte.

**La entrada canónica ya declaraba la regla que el bloque rompía.** `canonical.py`, en
`key="pib_real"`: *«el crecimiento (YoY del volumen) es invariante a la base»*. El panel
sectorial obedecía el registro; `bloque.py` no.

**Por qué nadie lo vio.** La muestra curada del producto publicaba `pib_real` = 3,41 % con
una brecha de −0,42 pp: coherente **en anual**. Producción emitía +0,74 % con −3,54 pp. La
muestra escrita a mano enseñaba cómo debería verse el número, no el que el pipeline produce.

Lo que este archivo fija es la propiedad, no el mecanismo: **el agregado contra el que se
reconcilia y los crecimientos que se reconcilian tienen que ser LA MISMA MEDIDA**. Da igual
por qué dejen de serlo.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import bloque as B
from modules.macro_monitor.forecasting import sectoral as S
from modules.macro_monitor.models.models import MacroSeries
from shared.database.base import Base

TRIMESTRES = [f"{a}-Q{q}" for a in range(2015, 2027) for q in (1, 2, 3, 4)][:44]
MESES = [f"{a}-{m:02d}" for a in range(2015, 2027) for m in range(1, 13)][:132]

#: Un índice con estacionalidad PURA y sin tendencia: cada trimestre del año repite su valor
#: año tras año. El interanual de una serie así es CERO en todos los trimestres; el
#: trimestral oscila ±20 %. Es el separador entre las dos medidas.
ESTACIONAL = {1: 90.0, 2: 100.0, 3: 95.0, 4: 120.0}


def _pib_del_bloque(db) -> dict:
    """La serie del PIB tal como el BVAR la estima, leída de la superficie pública del bloque.

    Se lee de `Y` y no de un interno: lo que importa es lo que el modelo consume.
    """
    armado = B.armar(db)
    j = armado.nombres.index("pib_real")
    return {t: fila[j] for t, fila in zip(armado.trimestres, armado.Y)}


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _pib_volumen(i: int, *, estacional: bool) -> float:
    """El índice de volumen del PIB en el trimestre `i`."""
    if estacional:
        return ESTACIONAL[int(TRIMESTRES[i][-1])]
    return 100.0 * (1.01 ** i)


def _sembrar(db, *, estacional: bool = False) -> None:
    """El mismo índice de volumen del PIB en los DOS cuadros, más lo que cada capa necesita.

    El mismo valor en `pib_2018` (el que lee el bloque) y en `pib_origen_2018` (el que lee el
    panel sectorial), a propósito: si las dos capas leen el MISMO número y aun así producen
    crecimientos distintos, la diferencia es de MEDIDA y no de fuente.
    """
    pesos = {c.clave: 1.0 + i for i, c in enumerate(S.COMPONENTES)}
    for i, t in enumerate(TRIMESTRES):
        pib_vol = _pib_volumen(i, estacional=estacional)
        # ── lo que lee el bloque del BVAR ──
        db.add(MacroSeries(series_code=B.panel_mod.PIB_CODE, period=t, value=pib_vol))
        db.add(MacroSeries(series_code="bcrd.xls.tasa_dolar_referencia_mc.promtrimestral.venta",
                           period=t, value=50.0 + i * 0.1))
        # ── lo que lee el panel sectorial ──
        total_nom = 0.0
        for j, c in enumerate(S.COMPONENTES):
            nom = pesos[c.clave] * 1000 * (1.02 ** i)
            db.add(MacroSeries(series_code=c.nominal, period=t, value=nom))
            db.add(MacroSeries(series_code=c.volumen, period=t,
                               value=pib_vol * (1.0 + 0.001 * (j % 5))))
            total_nom += nom
        db.add(MacroSeries(series_code=S.PIB_NOMINAL, period=t, value=total_nom))
        db.add(MacroSeries(series_code=S.PIB_VOLUMEN, period=t, value=pib_vol))
    for i, m in enumerate(MESES):
        db.add(MacroSeries(series_code="bcrd.xls.ipc_base_2019_2020."
                                       "variacion_porcentual_12_meses",
                           period=m, value=4.0 + i * 0.01))
        db.add(MacroSeries(series_code="bcrd.xls.serie_tpm.tasa_de_politica_monetaria",
                           period=m, value=5.0))
        db.add(MacroSeries(series_code="bcrd.xls.taap_activad.promedio_ponderado",
                           period=m, value=12.0))
    db.commit()


# ── la propiedad central ────────────────────────────────────────────────────────────

def test_el_pib_del_BLOQUE_y_el_del_panel_sectorial_son_la_MISMA_medida(db):
    """Mismo índice en las dos capas ⇒ mismo crecimiento. Si no, se están restando peras.

    Éste es el test que la lectura sectorial necesitaba y no tenía: nada en el repositorio
    afirmaba que `g_pib` y `panel.crecimiento` midieran lo mismo, y por eso el desacuerdo
    entre unidades pudo publicarse durante meses como si fuera un desacuerdo entre modelos.
    """
    _sembrar(db)
    del_bloque = _pib_del_bloque(db)
    panel = S.construir_panel(db)
    del_panel = dict(zip(panel.trimestres, panel.pib))

    comunes = sorted(set(del_bloque) & set(del_panel))
    assert len(comunes) >= 20, (
        f"solo {len(comunes)} trimestres en común: el fixture dejó de sostener la comparación")
    for t in comunes:
        assert del_bloque[t] == pytest.approx(del_panel[t], abs=0.02), (
            f"{t}: el bloque dice {del_bloque[t]:+.3f} % y el panel sectorial "
            f"{del_panel[t]:+.3f} % sobre EL MISMO índice. La reconciliación resta uno del "
            "otro, así que la diferencia entra al informe como «brecha contra el agregado»")


def test_la_ESTACIONALIDAD_no_se_publica_como_crecimiento(db):
    """Una serie sin tendencia y con estacionalidad pura crece 0 %, mire uno el trimestre que mire.

    Con la medida trimestral sobre la serie original, el mismo PIB «crecía» +23 % en un
    trimestre y −21 % en el siguiente por puro calendario, y el titular del informe dependía
    de en qué trimestre caía el horizonte.
    """
    _sembrar(db, estacional=True)
    serie = _pib_del_bloque(db)
    assert serie, "el bloque no produjo la serie del PIB"
    for t, v in serie.items():
        assert v == pytest.approx(0.0, abs=0.02), (
            f"{t}: un índice que repite el mismo valor cada año no crece, y el bloque "
            f"publica {v:+.2f} %. Eso es el calendario, no la economía")


def test_reconciliar_RECHAZA_un_agregado_que_no_es_la_misma_medida(db):
    """El guard en el punto de la resta, no solo en el origen de las series.

    Que hoy las dos capas coincidan no impide que mañana alguien cambie una de las dos. La
    medida viaja con el número y `reconciliar` la contrasta.
    """
    crudo = {"a": 4.0, "b": 5.0}
    pesos = {"a": 0.5, "b": 0.5}
    with pytest.raises(ValueError, match="medida"):
        S.reconciliar(crudo, pesos, 0.74, medida_del_agregado="trimestral")


def test_reconciliar_acepta_el_agregado_en_la_medida_del_panel(db):
    crudo = {"a": 4.0, "b": 5.0}
    pesos = {"a": 0.5, "b": 0.5}
    ajustado, brecha = S.reconciliar(crudo, pesos, 4.6,
                                     medida_del_agregado=S.MEDIDA_DEL_PANEL)
    assert brecha == pytest.approx(4.6 - 4.5)
    assert sum(pesos[k] * ajustado[k] for k in crudo) == pytest.approx(4.6)


# ── la muestra curada ───────────────────────────────────────────────────────────────

def test_la_MUESTRA_trae_las_mismas_claves_que_el_payload_real(db):
    """Una muestra escrita a mano que le falta una clave tapa el defecto en vez de mostrarlo.

    La muestra vieja traía solo `crecimiento`, así que enseñaba una tabla sectorial de una
    sola columna —la reconciliada— y el ajuste quedaba invisible. Y sus cifras eran
    coherentes **en anual** mientras el pipeline emitía trimestral: la vidriera mostraba el
    producto que uno querría, no el que la máquina produce.
    """
    from modules.macro_monitor import products_forecast as PF

    _sembrar(db)
    panel = S.construir_panel(db)
    pr = S.proyectar(panel, g_pib=panel.pib[-1], horizonte=panel.trimestres[-1],
                     origen_del_agregado="test", medida_del_agregado=S.MEDIDA_DEL_PANEL)
    # `clave` viaja desde #1152: es el identificador con el que `brechas` nombra a las
    # ausentes, y sin ella la muestra y el payload real no podían tener la misma forma.
    reales = {"clave", "etiqueta", "crecimiento", "crecimiento_sin_reconciliar", "peso",
              "incidencia"}
    assert {f for f in pr.sectores[0].__dataclass_fields__} >= reales

    for s in PF._SAMPLE_PAYLOAD["sectorial"]["sectores"]:
        assert set(s) == reales, (
            f"la muestra de «{s.get('etiqueta')}» trae {sorted(set(s))} y el payload real "
            f"trae {sorted(reales)}: la muestra enseña una tabla que el pipeline no produce")


def test_la_MUESTRA_es_ARITMETICAMENTE_coherente_consigo_misma(db):
    """El ajuste declarado tiene que ser la diferencia entre las dos columnas de cada fila.

    Sin esto la muestra puede declarar un ajuste y mostrar números que no lo reflejan, que es
    justo lo que la sección existe para hacer visible.
    """
    from modules.macro_monitor import products_forecast as PF

    sect = PF._SAMPLE_PAYLOAD["sectorial"]
    ajuste = sect["ajuste_pp"]
    for s in sect["sectores"]:
        delta = s["crecimiento"] - s["crecimiento_sin_reconciliar"]
        assert delta == pytest.approx(ajuste, abs=0.01), (
            f"«{s['etiqueta']}» pasa de {s['crecimiento_sin_reconciliar']:.2f} a "
            f"{s['crecimiento']:.2f} (Δ {delta:+.3f}) y la muestra declara un ajuste de "
            f"{ajuste:+.4f} pp")


def test_la_TABLA_publica_las_dos_columnas(db):
    """El campo existía con el comentario «se publica al lado»; la tabla no lo renderizaba."""
    from modules.macro_monitor import products_forecast as PF

    md = PF._md_sectorial(PF._SAMPLE_PAYLOAD)
    assert "proyectado" in md and "reconciliado" in md, md[:400]
    for s in PF._SAMPLE_PAYLOAD["sectorial"]["sectores"]:
        assert f"{s['crecimiento_sin_reconciliar']:.2f} %" in md, (
            f"la tabla no muestra el crecimiento SIN reconciliar de «{s['etiqueta']}»")
