"""El instrumento que decide si `solidez` ordena mal o si el panel mezcla poblaciones.

De este veredicto depende dónde se toca el score: en la curva del indicador (si la inversión
es del indicador) o en el universo sobre el que se mide (si la produce mezclar poblaciones).
Los dos arreglos son incompatibles, así que un instrumento que confunda los casos manda el
trabajo al lado equivocado. Estos tests fijan el caso de Simpson —cada estrato ordena bien y
el agregado sale invertido— y exigen que el veredicto salga «composicional».
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import modules.banking_score.models.models  # noqa: F401 — registra las tablas
import shared.auth.models  # noqa: F401 — destino de la FK
from modules.banking_score.models.models import (
    Bank, BankingData, BankType, ModelType, RatingResult,
)
from modules.banking_score.validation.composicion import (
    VEREDICTO_COMPOSICIONAL, VEREDICTO_INTRINSECO, _veredicto,
    diagnosticar_composicion,
)
from modules.banking_score.validation.metrics import (
    auc_estratificado, auc_low_score_risk, gini, spearman,
)
from shared.database.base import Base


# ── El AUC que solo cuenta pares comparables ──────────────────────

def test_con_un_solo_estrato_es_el_auc_de_siempre():
    """Si no hay a quién separar, estratificar no puede cambiar la cifra."""
    scores = [10.0, 20.0, 30.0, 40.0, 50.0]
    labels = [1, 1, 0, 0, 0]
    a, pares = auc_estratificado(scores, labels, ["unico"] * 5)
    assert a == auc_low_score_risk(scores, labels) == 1.0
    assert pares == 2 * 3  # eventos × no-eventos


def test_el_caso_de_simpson_es_exactamente_el_que_hay_que_distinguir():
    """Cada grupo ordena PERFECTO y el agregado sale invertido.

    Es la forma del hallazgo real: un grupo sobrecapitalizado (score alto) que además falla
    mucho, y uno menos capitalizado (score bajo) que casi no falla. Al agregarlos, los pares
    que cruzan grupos —que no informan sobre el ordenamiento— dominan la cuenta.
    """
    scores = [90.0] * 34 + [98.0] * 6 + [40.0] * 2 + [60.0] * 38
    labels = [1] * 34 + [0] * 6 + [1] * 2 + [0] * 38
    estratos = ["cambiaria"] * 40 + ["banca_multiple"] * 40

    agregado = gini(scores, labels)
    assert agregado is not None and agregado < -0.5  # invertido, y fuerte

    a, pares = auc_estratificado(scores, labels, estratos)
    assert a is not None
    assert round(2 * a - 1, 6) == 1.0            # dentro del estrato: ordena perfecto
    assert pares == 34 * 6 + 2 * 38              # solo los pares que comparten estrato


def test_sin_pares_comparables_lo_declara_en_vez_de_devolver_cero():
    """Un estrato por observación deja cero pares: eso es «no evaluable», no «Gini 0»."""
    a, pares = auc_estratificado([1.0, 2.0, 3.0], [1, 0, 1], ["a", "b", "c"])
    assert a is None
    assert pares == 0


def test_un_estrato_de_una_sola_clase_no_aporta_pares():
    scores = [10.0, 20.0, 30.0, 40.0]
    labels = [1, 0, 1, 1]
    # El estrato "b" es todo eventos → no aporta; solo cuenta el par del estrato "a".
    a, pares = auc_estratificado(scores, labels, ["a", "a", "b", "b"])
    assert a == 1.0
    assert pares == 1


# ── Spearman, que es como se ve el mecanismo supuesto ─────────────

def test_spearman_reconoce_el_orden_y_su_inverso():
    assert spearman([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]) == pytest.approx(1.0)
    assert spearman([1.0, 2.0, 3.0, 4.0], [40.0, 30.0, 20.0, 10.0]) == pytest.approx(-1.0)


def test_spearman_promedia_empates_y_declara_lo_constante():
    # Con empates el rango es el promedio; una serie constante no tiene correlación.
    assert spearman([1.0, 1.0, 2.0, 2.0], [5.0, 5.0, 9.0, 9.0]) == pytest.approx(1.0)
    assert spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
    assert spearman([1.0, 2.0], [1.0, 2.0]) is None  # menos de 3 pares


# ── El veredicto se computa de los dos intervalos ─────────────────

def _agg(g, lo, hi):
    return {"gini": g, "gini_ci": [lo, hi], "invertida": hi < 0, "concluyente": lo > 0}


def test_veredicto_composicional_cuando_la_inversion_no_sobrevive_al_estrato():
    v = _veredicto(_agg(-0.19, -0.26, -0.12), _agg(0.31, 0.20, 0.42))
    assert v["clave"] == "composicional"
    assert v["texto"] == VEREDICTO_COMPOSICIONAL


def test_veredicto_intrinseco_cuando_la_inversion_sobrevive_al_estrato():
    v = _veredicto(_agg(-0.19, -0.26, -0.12), _agg(-0.18, -0.25, -0.11))
    assert v["clave"] == "intrinseca"
    assert v["texto"] == VEREDICTO_INTRINSECO


def test_veredicto_parcial_cuando_se_achica_sin_cruzar_cero():
    v = _veredicto(_agg(-0.40, -0.50, -0.30), _agg(-0.10, -0.18, -0.02))
    assert v["clave"] == "parcial"


def test_sin_inversion_no_hay_nada_que_explicar():
    """Un IC que cruza cero no es una inversión, y el veredicto no debe inventarla."""
    assert _veredicto(_agg(-0.05, -0.20, 0.10), _agg(0.3, 0.2, 0.4))["clave"] == "sin_inversion"


def test_sin_pares_comparables_el_veredicto_lo_dice():
    sin_pares = {"gini": None, "gini_ci": None, "pares_comparables": 0,
                 "invertida": False, "concluyente": False}
    assert _veredicto(_agg(-0.19, -0.26, -0.12), sin_pares)["clave"] == "sin_pares"


# ── De punta a punta, sobre un panel con la forma del hallazgo ────

@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


P0, P1 = date(2024, 3, 31), date(2024, 6, 30)
_DETALLE = {k: {"raw": 1.0, "score": 55.0, "available": True}
            for k in ("solvencia", "tier1_ratio", "leverage",
                      "cobertura_provisiones", "patrimonio_activos")}


def _entidad(db, clave, tipo, solidez, activos, evento, con_detalle):
    """Una entidad con dos cortes → exactamente UNA observación del panel."""
    db.add(Bank(id=clave, name=f"E {clave}", bank_type=tipo))
    for p in (P0, P1):
        db.add(RatingResult(
            bank_id=clave, period_end=p, overall_score=solidez, solidez_score=solidez,
            model_type=ModelType.deterministic,
            indicator_details=_DETALLE if con_detalle else None,
        ))
    # El desenlace se dispara por la regla de CRÉDITO (la morosidad se duplica), que es la
    # única que necesita un solo trimestre de horizonte: así cada entidad aporta una
    # observación y el conteo del test es exacto.
    db.add(BankingData(bank_id=clave, period_end=P0, morosidad_pct=2.0, solvencia_pct=15.0,
                       activos_totales=activos, utilidad_neta=1))
    db.add(BankingData(bank_id=clave, period_end=P1, morosidad_pct=5.0 if evento else 2.0,
                       solvencia_pct=15.0, activos_totales=activos, utilidad_neta=1))


@pytest.fixture()
def panel_simpson(db):
    """Cambiarias: solidez alta y mucho evento. Bancos: solidez baja y casi ningún evento."""
    for i in range(34):
        _entidad(db, f"C{i}", BankType.cambiaria, 90, 100, evento=True, con_detalle=False)
    for i in range(6):
        _entidad(db, f"CS{i}", BankType.cambiaria, 98, 100, evento=False, con_detalle=False)
    for i in range(2):
        _entidad(db, f"B{i}", BankType.banca_multiple, 40, 100000, evento=True,
                 con_detalle=True)
    for i in range(38):
        _entidad(db, f"BS{i}", BankType.banca_multiple, 60, 100000, evento=False,
                 con_detalle=True)
    db.commit()
    return db


def test_el_diagnostico_llama_composicional_a_lo_que_lo_es(panel_simpson):
    salida = diagnosticar_composicion(panel_simpson, n_boot=200)
    assert salida["ok"] is True
    credito = salida["familias"]["credito"]
    assert credito["evaluable"] is True
    assert credito["eventos"] == 36

    assert credito["agregado"]["invertida"] is True          # el agregado ordena al revés
    assert credito["dentro_del_tipo_de_entidad"]["gini"] == 1.0   # cada tipo ordena perfecto
    assert credito["veredicto"]["clave"] == "composicional"


def test_una_regla_que_no_dispara_es_no_evaluable_y_no_un_gini_de_cero(panel_simpson):
    """El panel no tiene pérdidas sostenidas: eso NO es «no discrimina», es «sin evidencia»."""
    resultados = diagnosticar_composicion(panel_simpson, n_boot=50)["familias"]["resultados"]
    assert resultados["evaluable"] is False
    assert resultados["eventos"] == 0
    assert "gini" not in resultados


def test_el_estrato_sin_las_dos_clases_declara_el_motivo(panel_simpson):
    """Los bancos del panel casi no fallan: si un estrato queda de una sola clase, se dice."""
    salida = diagnosticar_composicion(panel_simpson, n_boot=50)
    por_tipo = {f["estrato"]: f for f in salida["familias"]["credito"]["por_tipo_de_entidad"]}
    assert set(por_tipo) == {"cambiaria", "banca_multiple"}
    # Ambos estratos tienen las dos clases en este panel, así que ambos traen Gini y N.
    assert por_tipo["cambiaria"]["n"] == 40
    assert por_tipo["cambiaria"]["solidez_mediana"] == 90.0
    assert por_tipo["banca_multiple"]["eventos"] == 2
    assert por_tipo["banca_multiple"]["fino"] is True  # 2 eventos: no se apoya nadie en eso


def test_las_entidades_con_otro_set_de_indicadores_se_cuentan_aparte(panel_simpson):
    """Una cambiaria no tiene `solvencia`/`tier1`: es otra población, no un hueco de dato."""
    panel = diagnosticar_composicion(panel_simpson, n_boot=50)["panel"]
    assert panel["n_con_dimension"] == 80
    assert panel["n_sin_indicadores_de_la_dimension"] == 40
    assert panel["tipos_de_entidad_en_el_panel"] == ["banca_multiple", "cambiaria"]


def test_la_correlacion_con_el_tamano_muestra_el_mecanismo(panel_simpson):
    """Más solidez ↔ entidad más chica es el mecanismo que la hipótesis supone."""
    corr = diagnosticar_composicion(panel_simpson, n_boot=50)["correlacion_dimension_vs_tamano"]
    assert corr["n"] == 80
    assert corr["spearman"] is not None and corr["spearman"] < -0.9


def test_sin_panel_lo_declara(db):
    salida = diagnosticar_composicion(db)
    assert salida["ok"] is False
    assert "sin panel" in salida["motivo"]


def test_una_dimension_inexistente_no_se_inventa(db):
    salida = diagnosticar_composicion(db, dimension="rentabilidad")
    assert salida["ok"] is False
    assert "desconocida" in salida["motivo"]


def test_medir_solo_sobre_quien_toma_credito_da_vuelta_el_signo(panel_simpson):
    """La cifra que un lector de banca espera: sin las poblaciones sin libro de crédito.

    No reemplaza al veredicto —es otro universo, más chico— pero es la que responde «¿y si la
    credencial se midiera solo sobre entidades comparables con un banco?».
    """
    credito = diagnosticar_composicion(panel_simpson, n_boot=200)["familias"]["credito"]
    solo = credito["solo_entidades_con_libro_de_credito"]
    assert solo["n"] == 40                      # las 40 cambiarias quedaron fuera
    assert solo["eventos"] == 2
    assert solo["gini"] == 1.0                  # el agregado decía −0,6; acá ordena perfecto
    assert solo["excluye"] == ["cambiaria", "fiduciaria"]


def test_el_desglose_por_indicador_declara_que_su_poblacion_es_otra(panel_simpson):
    """Solo las entidades del set estándar tienen `solvencia`/`tier1`: el N lo tiene que decir."""
    credito = diagnosticar_composicion(panel_simpson, n_boot=50)["familias"]["credito"]
    solvencia = credito["por_indicador"]["solvencia"]
    assert solvencia["n"] == 40                 # no las 80 de la dimensión
    assert solvencia["eventos"] == 2
