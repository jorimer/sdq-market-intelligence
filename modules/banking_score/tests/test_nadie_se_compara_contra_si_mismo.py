"""Una entidad no entra en la referencia que la juzga.

**El defecto, en dos lugares.** Apareció primero en el mapa sectorial: la mora de la entidad
se comparaba contra la del sector ENTERO, que la incluye. Se corrigió ahí. Al preguntarse
dónde más vivía el mismo patrón apareció `panel_benchmarks`, que computa la mediana del grupo
de pares incluyendo a la entidad evaluada.

**El sesgo va SIEMPRE en la misma dirección** —hacia «no está tan lejos del grupo»— y eso es
lo que lo vuelve un defecto y no ruido. Medido sobre los dieciséis bancos múltiples de
producción: la mediana de ROE pasa de 12,653 con la entidad a 13,229 sin ella; la de
cost-to-income de 53,611 a 54,462; la de morosidad de 1,975 a 1,890.

Es MENOR que en el mapa —donde el promedio ponderado por deuda daba 3,3 puntos sobre una
brecha de 10— porque una mediana sobre dieciséis se mueve poco al quitar una observación.
Pequeño no es cero, y la dirección es la misma.

**Dónde NO aplica, y por qué se declara.** El sujeto de un boletín de sistema ES el sistema:
su promedio los incluye a todos por definición. La exclusión existe para que una ENTIDAD no
se compare contra sí misma; sin entidad no hay nada que excluir.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — registra users para las FK
from shared.database.base import Base
from modules.banking_score.models.models import (
    Bank, BankType, ModelType, RatingResult,
)
from modules.banking_score.scoring.benchmarks import panel_benchmarks

CORTE = date(2026, 3, 31)


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


@pytest.fixture()
def panel(db):
    """Siete bancos múltiples: seis con morosidad baja y el sujeto con una alta.

    Siete y no cinco a propósito: `MIN_N` es 5, así que con cinco el grupo cae por debajo
    del mínimo al excluir al sujeto y el benchmark se OMITE — comportamiento correcto que
    tiene su propio test más abajo, pero que taparía el efecto que este panel mide.
    """
    sujeto = None
    for i, mora in enumerate((1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 9.0)):
        b = Bank(name=f"Banco {i}", bank_type=BankType.banca_multiple, is_active=True)
        db.add(b)
        db.flush()
        db.add(RatingResult(
            bank_id=b.id, period_end=CORTE, model_type=ModelType.deterministic,
            overall_score=70.0, solidez_score=70, calidad_score=70, eficiencia_score=70,
            liquidez_score=70, diversificacion_score=70,
            indicator_details={"morosidad": {"raw": mora, "score": 50, "available": True}}))
        if mora == 9.0:
            sujeto = b
    db.commit()
    return db, sujeto


#: El registro traduce el indicador `morosidad` a la clave de benchmark `npl`. Se lee del
#: propio mapeo en vez de escribirla: si el registro la renombra, el test sigue midiendo lo
#: que quiere medir en vez de fallar por un nombre.
from shared.data.sib_client import INDICATOR_TO_BENCHMARK

_CLAVE_MORA = f"{INDICATOR_TO_BENCHMARK['morosidad']}_avg"


def _mora(bench):
    return (bench.get("peer_groups", {}).get("banca_multiple", {}) or {}).get(_CLAVE_MORA)


class TestLaEntidadNoEntraEnSuPropiaReferencia:
    def test_incluirla_ARRASTRA_la_mediana_hacia_ella(self, panel):
        db, sujeto = panel
        con = _mora(panel_benchmarks(db, CORTE))
        sin = _mora(panel_benchmarks(db, CORTE, excluir_bank_id=str(sujeto.id)))
        assert con is not None and sin is not None
        # Con el sujeto (mora 9,0) la mediana de siete es 1,8; sin él, la de seis es 1,65.
        assert con == pytest.approx(1.8, abs=.01)
        assert sin == pytest.approx(1.65, abs=.01)
        assert con > sin, "la mediana con el sujeto debe estar más cerca de él"

    def test_la_brecha_del_sujeto_CRECE_al_excluirlo(self, panel):
        """Es el punto entero: la referencia que lo incluye le perdona parte de su brecha."""
        db, sujeto = panel
        con = _mora(panel_benchmarks(db, CORTE))
        sin = _mora(panel_benchmarks(db, CORTE, excluir_bank_id=str(sujeto.id)))
        assert (9.0 - sin) > (9.0 - con)

    def test_la_procedencia_DECLARA_contra_qué_se_comparó(self, panel):
        """Sin el campo, la narrativa no puede distinguir una referencia que excluye al
        sujeto de una que lo incluye, y son cosas distintas."""
        db, sujeto = panel
        assert panel_benchmarks(db, CORTE, excluir_bank_id=str(sujeto.id))[
            "procedencia"]["excluye_a_la_entidad_evaluada"] is True
        assert panel_benchmarks(db, CORTE)["procedencia"][
            "excluye_a_la_entidad_evaluada"] is False

    def test_un_id_que_no_esta_en_el_panel_no_cambia_nada(self, panel):
        db, _ = panel
        assert _mora(panel_benchmarks(db, CORTE, excluir_bank_id="no-existe")) == \
            _mora(panel_benchmarks(db, CORTE))


class TestLasRutasQueEmitenUnInformeLaExcluyen:
    """El cómputo correcto que nadie invoca no arregla nada: van cinco defectos así."""

    @pytest.mark.parametrize("archivo", [
        "modules/banking_score/products.py",
        "modules/banking_score/api/router_reports.py",
        "modules/banking_score/reports/revision_anual.py",
    ])
    def test_pasan_la_entidad_al_pedir_la_referencia(self, archivo):
        import pathlib
        src = pathlib.Path(archivo).read_text()
        assert "excluir_bank_id=str(bank.id)" in src, (
            f"«{archivo}» pide la referencia sin excluir a la entidad: se compara contra sí "
            f"misma")

    def test_un_boletin_de_SISTEMA_no_excluye_a_nadie(self):
        """Su sujeto ES el sistema y el promedio los incluye a todos por definición."""
        import pathlib
        src = pathlib.Path("modules/banking_score/api/router_reports.py").read_text()
        i = src.index("if benchmarks is None and report_type in _NARRATED_SYSTEM_TYPES")
        assert "panel_benchmarks(db, pe)" in src[i:i + 600]
        assert "excluir_bank_id" not in src[i:i + 600]


class TestUnGrupoQueQUEDA_CORTO_no_publica_una_referencia_sesgada:
    """Excluir al sujeto puede dejar al grupo por debajo del mínimo de observaciones.

    Pasa en los estratos chicos —corporaciones de crédito son tres— y la salida correcta es
    OMITIR el benchmark, no volver al que incluye al sujeto: declarar la brecha es mejor que
    publicar un número que se compara contra sí mismo. `MIN_N` ya lo hace; esto lo fija para
    que nadie lo «arregle» rellenando.
    """

    def test_con_cinco_al_excluir_uno_el_grupo_desaparece(self, db):
        sujeto = None
        for i, mora in enumerate((1.0, 1.5, 2.0, 2.5, 9.0)):
            b = Bank(name=f"Chico {i}", bank_type=BankType.corporacion_credito,
                     is_active=True)
            db.add(b)
            db.flush()
            db.add(RatingResult(
                bank_id=b.id, period_end=CORTE, model_type=ModelType.deterministic,
                overall_score=70.0, solidez_score=70, calidad_score=70, eficiencia_score=70,
                liquidez_score=70, diversificacion_score=70,
                indicator_details={"morosidad": {"raw": mora, "score": 50,
                                                 "available": True}}))
            if mora == 9.0:
                sujeto = b
        db.commit()
        bench = panel_benchmarks(db, CORTE, excluir_bank_id=str(sujeto.id))
        grupo = bench.get("peer_groups", {}).get("corporacion_credito") or {}
        assert _CLAVE_MORA not in grupo, (
            "con cuatro observaciones no se publica una mediana de grupo")
