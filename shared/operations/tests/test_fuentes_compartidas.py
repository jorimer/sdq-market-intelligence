"""Las fuentes regionales que viajan dentro de informes de OTROS ejes tienen fila en el sensor.

Producción, 2026-09-15: el cubo de crédito de la SIB iba 168 días atrás, la ocupación por rama
seguía en 2024 y SIUBEN servía una instantánea — y el sensor, que pregunta a cada producto por
SU dato, no tenía una fila para ninguna.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.operations.fuentes_congeladas import (
    AL_DIA, CONGELADA, EJE_COMPARTIDAS, INDETERMINADA, _fuentes_compartidas,
    _veredictos_compartidos, fin_del_periodo, leer_fuentes_de_los_ejes, resumen_de_fuentes)


@pytest.fixture()
def db():
    import app.main  # noqa: F401 — registra todas las tablas
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    try:
        yield s
    finally:
        s.close()


@pytest.mark.parametrize("periodo,esperado", [
    ("2026-03-31", date(2026, 3, 31)),
    ("2026-Q1", date(2026, 3, 31)),
    ("2025-Q4", date(2025, 12, 31)),
    ("2026-02", date(2026, 2, 28)),
    ("2024-02", date(2024, 2, 29)),
    ("2025", date(2025, 12, 31)),
])
def test_el_fin_de_cada_forma_de_periodo(periodo, esperado):
    assert fin_del_periodo(periodo) == esperado


@pytest.mark.parametrize("basura", [None, "", "2026-Q5", "2026-13", "no-es-fecha", "25"])
def test_un_periodo_ilegible_no_inventa_fecha(basura):
    assert fin_del_periodo(basura) is None


def test_las_fuentes_que_se_repartieron_estan_TODAS_declaradas():
    claves = {f.clave for f in _fuentes_compartidas()}
    assert claves >= {"cubo_de_credito", "encft_por_dominio", "encft_trimestral", "ipc_por_quintil",
                      "salario_tss", "encft_ocupacion_por_rama", "siuben_provincial"}


def test_sin_dato_TODAS_quedan_indeterminadas_y_ninguna_al_dia(db):
    vs = _veredictos_compartidos(db)
    assert len(vs) == len(_fuentes_compartidas())
    assert {v.estado for v in vs} == {INDETERMINADA}, [(v.clave, v.motivo) for v in vs]


def test_llegan_al_BARRIDO_y_al_resumen_con_su_id(db):
    ids = {v.id for v in leer_fuentes_de_los_ejes(db) if v.eje == EJE_COMPARTIDAS}
    assert "compartidas:cubo_de_credito" in ids
    assert "compartidas:cubo_de_credito" in resumen_de_fuentes(db)["indeterminadas"]


def _sembrar_dominio(db, periodo):
    from modules.social_dev.models.models import SocialIndicator
    db.add(SocialIndicator(theme="subutilizacion_su4_regional_anual", entity_key="sur",
                           period=periodo, value=14.0, unit="%", source="BCRD"))
    db.commit()


def test_de_punta_a_punta_la_ENCFT_regional_de_2023_se_marca_CONGELADA(db):
    _sembrar_dominio(db, "2023")
    v = next(x for x in _veredictos_compartidos(db, hoy=date(2026, 9, 15))
             if x.clave == "encft_por_dominio")
    assert v.estado == CONGELADA and "2023" in v.detalle_del_producto
    assert v.fuentes == ("BCRD · ENCFT",)


def test_el_mismo_camino_con_el_anio_anterior_sale_AL_DIA(db):
    _sembrar_dominio(db, "2025")
    v = next(x for x in _veredictos_compartidos(db, hoy=date(2026, 9, 15))
             if x.clave == "encft_por_dominio")
    assert v.estado == AL_DIA, v.motivo


def test_un_trimestre_se_mide_desde_su_CIERRE_y_no_desde_su_inicio(db):
    """2026-Q1 cierra el 31 de marzo: al 15 de septiembre son 168 días, sobre el tope de 150."""
    from modules.social_dev.models.models import SocialIndicator
    db.add(SocialIndicator(theme="informality_rate_trimestral", period="2026-Q1", value=54.1,
                           unit="%", source="BCRD"))
    db.commit()
    v = next(x for x in _veredictos_compartidos(db, hoy=date(2026, 9, 15))
             if x.clave == "encft_trimestral")
    assert v.dias_desde_el_periodo_del_dato == 168 and v.estado == CONGELADA


def test_el_salario_minimo_de_diciembre_NO_se_marca_congelado_en_septiembre(db):
    """Producción, 2026-09-15: con cadencia mensual la fila 2025-12 salía congelada (258 días) y
    avisaba a los administradores cada mes. La serie solo cambia por decreto y se publica al
    cierre del año: es una fuente anual."""
    from modules.social_dev.models.models import SocialIndicator
    from shared.capacidad_de_pago import _TEMA_SALARIO_REFERENCIA
    db.add(SocialIndicator(theme=_TEMA_SALARIO_REFERENCIA, entity_key="salario_minimo",
                           period="2025-12", value=27989.0, unit="RD$/mes", source="MHE"))
    db.commit()
    v = next(x for x in _veredictos_compartidos(db, hoy=date(2026, 9, 15))
             if x.clave == "salario_minimo")
    assert v.cadencia == "annual" and v.estado == AL_DIA, v.motivo
