"""El ledger tiene que saber contra QUÉ puntúa. Dos defectos que salieron juntos.

**A · Las proyecciones del BVAR no se pueden puntuar nunca.** `emision.OBJETIVO` es
``"pib_real"``, que es el nombre de la variable DENTRO del bloque —no un `series_code`—, y
viaja al ledger como `target_series`. `puntuar_pendientes` lo busca en `mm_series`, donde no
existe. Verificado en producción: `GET /api/v1/macro-monitor/series/pib_real` devuelve
``observations: []``. Toda fila del BVAR queda `pending` para siempre y la sección de
desempeño publica «ninguna alcanzó su período de cierre», que se lee como «los trimestres no
cerraron» cuando la verdad es que **no pueden cerrar**.

**B · El ledger puntúa una TASA contra un NIVEL.** El punto que guardan los dos motores es un
Δlog en % (~0,4); la serie contra la que se compara es el ÍNDICE DE VOLUMEN del PIB (~133).
Un nowcast puntuado daría `abs_error ≈ 132,75`, y eso se publicaría como RMSE.

B no explotó todavía SOLO porque A mantiene la sección vacía. Los dos se arreglan juntos: A
sin B publica un RMSE de ~130 en la primera corrida.

Este archivo pasa por la API pública —`emision.emitir` y `ledger.puntuar_pendientes`— y no
por dentro de la implementación, a propósito: un test del motor no es un test de la ruta, y
acá lo que falla es el CAMINO entre los dos.
"""
from datetime import date

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import bloque, desempeno, emision, ledger, nowcast
from modules.macro_monitor.forecasting import panel as panel_mod
from modules.macro_monitor.forecasting.models import ForecastLog
from modules.macro_monitor.models.models import MacroSeries
from shared.database.base import Base

PIB = panel_mod.PIB_CODE

#: El corte de emisión. 2026-Q3 sigue abierto (cierra el 30-sep), así que los pronósticos
#: que lo apuntan SÍ se escriben — `_es_hacia_adelante` descarta los vencidos.
CORTE = date(2026, 8, 15)

#: El índice de volumen del PIB en los tres trimestres que el observado va a traer. Hacen
#: falta TRES porque los dos motores miden distinto contra la misma serie, y ésa es
#: justamente la razón por la que la medida tiene que viajar con el punto:
#:
#: * el **nowcast** emite la variación contra el trimestre ANTERIOR (`dlog_pct`);
#: * el **BVAR** emite la variación contra el mismo trimestre del año anterior (`yoy_pct`),
#:   porque el índice que publica el BCRD es la serie ORIGINAL y su variación trimestral
#:   arrastra 5,80 pp de estacionalidad pura.
INDICE_Q3_ANTERIOR, INDICE_Q2, INDICE_Q3 = 128.0, 133.0, 133.5
DLOG_OBSERVADO = (np.log(INDICE_Q3) - np.log(INDICE_Q2)) * 100   # ≈ 0,3754 %
YOY_OBSERVADO = (INDICE_Q3 / INDICE_Q3_ANTERIOR - 1) * 100       # ≈ 4,2969 %

#: Lo que el nowcast dice. Se elige CERCA del observado para que el error correcto sea
#: chico: si el arreglo funciona, `abs_error` es ~0,005; si el ledger sigue comparando la
#: tasa contra el nivel, es ~133.
PUNTO_NOWCAST = 0.38


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _observar(db, periodo, valor):
    db.add(MacroSeries(series_code=PIB, period=periodo, value=valor))
    db.commit()


def _bloque_sintetico() -> bloque.BloqueArmado:
    """Un bloque de juguete con la MISMA forma que el real: 60 trimestres × 5 variables, y
    el PIB en variación logarítmica ×100 —que es como `bloque._transformar` lo entrega—.

    Determinista a propósito: un bloque aleatorio hace que el punto del BVAR cambie entre
    corridas y el test deje de significar lo mismo dos veces seguidas.
    """
    trimestres, filas = [], []
    # Termina en 2026-Q2: el último trimestre que el BCRD tenía publicado al corte. Así el
    # primer horizonte del BVAR es 2026-Q3, que al 15 de agosto sigue ABIERTO — un horizonte
    # ya cerrado no entra al ledger, y con el bloque terminando antes el test no probaría la
    # emisión sino el descarte por vencido.
    for i in range(60):
        a, q = divmod(2011 * 4 + 2 + i, 4)          # (2011-Q3) + i, 60 trimestres → 2026-Q2
        trimestres.append(f"{a}-Q{q + 1}")
        onda = np.sin(i / 3.0)
        filas.append((
            4.30 + 0.30 * onda,           # pib_real       · variación interanual %
            4.00 + 0.50 * np.cos(i / 4.0),  # inflacion      · nivel %
            6.00 + 0.40 * onda,           # tpm            · nivel %
            1.00 + 0.20 * np.cos(i / 5.0),  # tipo_cambio    · Δlog ×100
            12.0 + 0.60 * onda,           # tasa_activa    · nivel %
        ))
    nombres = tuple(v.nombre for v in bloque.BLOQUE)
    return bloque.BloqueArmado(
        trimestres=tuple(trimestres), nombres=nombres, Y=tuple(filas),
        inicio_por_variable={n: trimestres[0] for n in nombres},
        fin_por_variable={n: trimestres[-1] for n in nombres},
    )


@pytest.fixture()
def emitido(db, monkeypatch):
    """El estado real del producto: un corte emitido, con el nowcast y el BVAR.

    Solo se sustituye el ARMADO del bloque —traer las cinco series del BCRD a una matriz—;
    el BVAR, la emisión y el ledger corren de verdad.
    """
    _observar(db, "2025-Q3", INDICE_Q3_ANTERIOR)
    _observar(db, "2026-Q2", INDICE_Q2)

    def _estimar(_db, _corte, *, variante, **_kw):
        if variante != 2:
            return None
        return nowcast.Nowcast(
            model_id="bridge_imae_pib.m2.v1", target_series=PIB, horizon="2026-Q3",
            as_of=CORTE.isoformat(), point=PUNTO_NOWCAST,
            intervals=[[0.80, PUNTO_NOWCAST - 0.9, PUNTO_NOWCAST + 0.9],
                       [0.90, PUNTO_NOWCAST - 1.2, PUNTO_NOWCAST + 1.2]],
            n_train=55)

    monkeypatch.setattr(emision.nowcast, "estimar", _estimar)
    monkeypatch.setattr(emision.bloque, "armar", lambda _db, **_kw: _bloque_sintetico())
    em = emision.emitir(db, as_of=CORTE)
    assert em.escritos >= 2, f"la emisión no escribió nada que puntuar: {em.motivos}"
    return em


# ── A · lo que se emite tiene que poder puntuarse ───────────────────────────────────


def test_el_bvar_apunta_a_una_serie_QUE_EXISTE(db, emitido):
    """`pib_real` no es un `series_code`: es el nombre de la variable en el bloque. Una fila
    que lo declara como objetivo no se puede puntuar contra nada, nunca."""
    codigos = {str(f.target_series) for f in db.query(ForecastLog).all()}
    huerfanas = {c for c in codigos
                 if db.query(MacroSeries).filter_by(series_code=c).count() == 0}
    assert not huerfanas, (
        f"el ledger guardó pronósticos contra series que no existen: {sorted(huerfanas)}. "
        "Esas filas quedan `pending` para siempre y la sección de desempeño lo publica como "
        "«todavía no cerraron», que es otra cosa")


def test_al_llegar_el_observado_las_filas_del_corte_SE_PUNTUAN(db, emitido):
    """El invariante del producto entero: si nada se puede puntuar, el track record no
    arranca nunca y el eje prospectivo es decorativo."""
    _observar(db, "2026-Q3", INDICE_Q3)
    puntuados = ledger.puntuar_pendientes(db)
    assert puntuados >= 2, (
        f"llegó el observado de 2026-Q3 y se puntuaron {puntuados} filas. Los pronósticos "
        "de ese trimestre —el nowcast y el BVAR a un trimestre vista— tenían que cerrar")


# ── B · se puntúa contra la MISMA medida ────────────────────────────────────────────


def test_una_TASA_no_se_puntua_contra_un_NIVEL(db, emitido):
    """El punto es un Δlog en % (~0,4). La serie es el índice de volumen (~133). Comparar
    uno con otro da un error del tamaño del índice, y eso se publica como RMSE."""
    _observar(db, "2026-Q3", INDICE_Q3)
    ledger.puntuar_pendientes(db)
    puntuadas = db.query(ForecastLog).filter(ForecastLog.status == "scored").all()
    assert puntuadas, "no hay ninguna fila puntuada: el defecto A tapa al B"
    peor = max(float(f.abs_error) for f in puntuadas)
    assert peor < 5.0, (
        f"el peor error absoluto de la corrida es {peor:.2f}. Un pronóstico de crecimiento "
        f"trimestral se equivoca por décimas de punto; {peor:.2f} es el tamaño del ÍNDICE, "
        "o sea que se comparó una tasa contra un nivel")


def test_el_observado_que_se_guarda_esta_en_la_medida_DEL_PUNTO(db, emitido):
    """`realized` es lo que hace auditable el error. Si guarda el nivel mientras el punto es
    una tasa, la fila miente por sí sola aunque nadie mire el RMSE.

    Y los DOS motores se realizan distinto sobre la MISMA serie y el MISMO trimestre: el
    nowcast contra 2026-Q2 y el BVAR contra 2025-Q3. Si la medida no viajara con la fila, uno
    de los dos tendría que estar mal — y el que se equivocara no lo diría.
    """
    _observar(db, "2026-Q3", INDICE_Q3)
    ledger.puntuar_pendientes(db)
    puntuadas = {str(f.model_id).split(".")[0]: f
                 for f in db.query(ForecastLog)
                 .filter(ForecastLog.status == "scored",
                         ForecastLog.horizon == "2026-Q3").all()}

    nowcast_fila = puntuadas.get("bridge_imae_pib")
    assert nowcast_fila is not None, "el nowcast de 2026-Q3 no se puntuó"
    assert float(nowcast_fila.realized) == pytest.approx(DLOG_OBSERVADO, abs=1e-6), (
        f"`realized` del nowcast guardó {nowcast_fila.realized}, y lo observado en su medida "
        f"es {DLOG_OBSERVADO:.4f} % — la variación contra 2026-Q2, no el índice")

    bvar_fila = puntuadas.get("bvar_minnesota")
    assert bvar_fila is not None, "el pronóstico del BVAR a un trimestre vista no se puntuó"
    assert float(bvar_fila.realized) == pytest.approx(YOY_OBSERVADO, abs=1e-6), (
        f"`realized` del BVAR guardó {bvar_fila.realized}, y lo observado en su medida es "
        f"{YOY_OBSERVADO:.4f} % — la variación contra 2025-Q3, no contra 2026-Q2")
    assert float(nowcast_fila.realized) != pytest.approx(float(bvar_fila.realized)), (
        "los dos motores se realizaron IGUAL sobre la misma serie y el mismo trimestre: la "
        "medida de la fila no está decidiendo nada")


# ── El instrumento no puede decir «todavía no» cuando la verdad es «nunca» ──────────


def test_la_seccion_no_dice_que_los_trimestres_no_cerraron_cuando_NO_PUEDEN_cerrar(db):
    """Una fila que apunta a una serie inexistente no está esperando: está rota. La sección
    tiene que nombrar la causa — un veto silencioso se lee como que el eje no tiene
    validación."""
    ledger.registrar(db, model_id="bvar_minnesota.5v.v1", target_series="pib_real",
                     horizon="2026-Q3", as_of="2026-08-15", point=1.2,
                     intervals=[[0.80, 0.3, 2.1]], h=1,
                     **_medida_si_existe())
    texto = desempeno.seccion(db)
    assert "ninguna de las proyecciones emitidas alcanzó su período de cierre" not in texto, (
        "la sección dice que los trimestres no cerraron. La fila pendiente apunta a una "
        "serie que no existe: no puede cerrar nunca, y decir lo primero es mentir con el "
        "instrumento")


def _medida_si_existe() -> dict:
    """`registrar` exige la medida después del arreglo y no la conoce antes. Este test mide
    la SECCIÓN, no la firma: sin esto fallaría por `TypeError` en las dos versiones y no
    probaría nada."""
    import inspect
    if "measure" in inspect.signature(ledger.registrar).parameters:
        from shared.data import medida_de_pronostico as medida
        return {"measure": medida.DLOG_PCT}
    return {}
