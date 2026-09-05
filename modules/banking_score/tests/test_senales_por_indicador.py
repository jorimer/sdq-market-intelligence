"""La procedencia por indicador del Banking Score, y el peso con el que se declara.

**El defecto que lo obligó.** Sin `variable_signals`, el eje caía a
`_product_level_fallback`: una sola señal agregada cuyo `real_fraction` es la cobertura a
nivel FUENTE, o sea 1.0 en cuanto haya una entidad calificada. La nota metodológica que se
genera de ahí afirmaba «100% del peso de este índice se sostiene en dato real» sobre un eje
donde hay indicadores sin dato en todo el panel. No era una nota pobre: era una
sobreafirmación sobre nuestra propia cobertura, y el boletín regional la publica a una lista
de correo.

**Por qué el peso importa tanto como el estado.** La cobertura es PONDERADA. Un indicador de
Solidez sin dato pesa el triple que uno de Diversificación, así que una tabla de pesos
equivocada no da un número feo: da un número creíble y falso.
"""
import datetime as dt
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401 — registra todos los modelos antes del create_all
from modules.banking_score.models.models import Bank, BankType, ModelType, RatingResult
from modules.banking_score.products import BankingProduct
from modules.banking_score.scoring.weights import (
    CALIDAD_INDICATORS, DIVERSIFICACION_INDICATORS, EFICIENCIA_INDICATORS,
    LIQUIDEZ_INDICATORS, SOLIDEZ_FAMILIAS, SOLIDEZ_INDICATORS, SUB_COMPONENT_WEIGHTS,
    WEIGHT_PROFILES, peso_efectivo_por_indicador,
)
from shared.database.base import Base

PERIODO = dt.date(2026, 6, 30)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    sesion = sessionmaker(bind=engine, autoflush=False)()
    yield sesion
    sesion.close()


def _panel(db, n=10, sin_dato=(), parcial=None):
    """Un panel de *n* entidades. *sin_dato*: indicadores que NADIE tiene.

    *parcial*: ``{indicador: cuántas entidades lo tienen}``.
    """
    parcial = parcial or {}
    claves = list(peso_efectivo_por_indicador())
    for i in range(n):
        banco = Bank(id=str(uuid.uuid4()), name=f"Banco {i}", sib_code=f"B{i}",
                     bank_type=BankType.banca_multiple)
        db.add(banco)
        db.flush()
        detalle = {}
        for clave in claves:
            if clave in sin_dato:
                disponible = False
            elif clave in parcial:
                disponible = i < parcial[clave]
            else:
                disponible = True
            detalle[clave] = {"raw": 1.0 if disponible else None,
                              "score": 50.0 if disponible else None,
                              "available": disponible}
        db.add(RatingResult(id=str(uuid.uuid4()), bank_id=banco.id, period_end=PERIODO,
                            model_type=ModelType.deterministic, indicator_details=detalle,
                            overall_score=60.0))
    db.commit()
    return db


class TestLosPesos:
    """Se DERIVAN de las constantes del motor. Copiarlos a mano fue lo que se evitó acá."""

    @pytest.mark.parametrize("tipo", [None, *WEIGHT_PROFILES])
    def test_suman_uno(self, tipo):
        assert sum(peso_efectivo_por_indicador(tipo).values()) == pytest.approx(1.0)

    @pytest.mark.parametrize("dimension,indicadores", [
        ("solidez", SOLIDEZ_INDICATORS), ("calidad", CALIDAD_INDICATORS),
        ("eficiencia", EFICIENCIA_INDICATORS), ("liquidez", LIQUIDEZ_INDICATORS),
        ("diversificacion", DIVERSIFICACION_INDICATORS),
    ])
    def test_cada_dimension_conserva_su_peso(self, dimension, indicadores):
        pesos = peso_efectivo_por_indicador()
        suma = sum(pesos[i] for i in indicadores)
        assert suma == pytest.approx(SUB_COMPONENT_WEIGHTS[dimension])

    def test_solidez_reparte_por_familia_y_no_por_indicador(self):
        """Un hecho, un voto: `solvencia`, `tier1_ratio` y `leverage` miden lo mismo.

        Si se repartiera `0.40 / 5`, la adecuación de capital pesaría el 60% de Solidez —
        que es exactamente el defecto que las familias vinieron a cerrar.
        """
        pesos = peso_efectivo_por_indicador()
        por_familia = SUB_COMPONENT_WEIGHTS["solidez"] / len(SOLIDEZ_FAMILIAS)
        assert pesos["patrimonio_activos"] == pytest.approx(por_familia)
        assert pesos["solvencia"] == pytest.approx(por_familia / 3)
        assert pesos["solvencia"] != pytest.approx(SUB_COMPONENT_WEIGHTS["solidez"] / 5)

    def test_el_compuesto_de_calidad_no_pesa(self):
        """`composite_calidad` es la media de los siete de Calidad: si pesara, cada hecho
        contaría dos veces."""
        assert "composite_calidad" not in peso_efectivo_por_indicador()


class TestLasSeñales:
    def test_el_eje_deja_de_estar_degradado(self, db):
        """El criterio de aceptación de T-BR-10."""
        from shared.registry.service import build_data_registry

        _panel(db)
        eje = next(a for a in build_data_registry(db).axes if a.sector_key == "banking")
        assert not eje.degraded
        assert len(eje.signals) == len(peso_efectivo_por_indicador())

    def test_un_indicador_sin_dato_en_NADIE_es_brecha(self, db):
        _panel(db, sin_dato=("migracion",))
        señales = {s.key: s for s in BankingProduct(db).variable_signals()["signals"]}
        assert señales["migracion"].state == "gap"
        assert señales["migracion"].real_fraction == 0.0
        assert "brecha" in señales["migracion"].note

    def test_la_cobertura_parcial_se_declara_con_su_fraccion(self, db):
        """Una variable con dato en 3 de 10 es REAL, pero aporta 0,3 — no 1."""
        _panel(db, parcial={"exposicion_re": 3})
        señales = {s.key: s for s in BankingProduct(db).variable_signals()["signals"]}
        assert señales["exposicion_re"].state == "real"
        assert señales["exposicion_re"].real_fraction == 0.3
        assert "3/10" in señales["exposicion_re"].note

    def test_la_cobertura_ponderada_baja_con_lo_que_falta(self, db):
        """Y baja EN PROPORCIÓN AL PESO: es la diferencia entre una nota honesta y una
        creíble pero falsa."""
        from shared.registry.signals import AxisRegistry

        _panel(db, sin_dato=("migracion",))
        r = BankingProduct(db).variable_signals()
        eje = AxisRegistry(sector_key="banking", display_name="x", source="y",
                           implemented=True, signals=tuple(r["signals"]))
        peso_ausente = peso_efectivo_por_indicador()["migracion"]
        # `coverage_real` viene redondeado a 4 decimales por el propio registro.
        assert eje.coverage_real == pytest.approx(1.0 - peso_ausente, abs=1e-4)

    def test_todos_los_indicadores_diferencian_entre_entidades(self, db):
        """`per_subject` en todos: ninguno es un dato nacional que valga igual para el panel.

        El `scope` existe para no decirle a una entidad que algo explica su posición cuando
        no la explica.
        """
        _panel(db)
        assert all(s.scope == "per_subject"
                   for s in BankingProduct(db).variable_signals()["signals"])

    def test_sin_panel_no_inventa_señales(self, db):
        """Sin ratings, degrada con honestidad en vez de emitir un cero."""
        assert BankingProduct(db).variable_signals() == {"period": None, "signals": []}


class TestLaNotaQueSeVaAPublicar:
    def test_deja_de_afirmar_el_cien_por_ciento(self, db):
        """La regresión concreta: el fallback publicaba «100% … dato real»."""
        from shared.registry.provenance import provenance_paragraph
        from shared.registry.service import build_data_registry

        _panel(db, sin_dato=("migracion",), parcial={"exposicion_re": 3})
        eje = next(a for a in build_data_registry(db).axes if a.sector_key == "banking")
        texto = provenance_paragraph(eje)
        assert not texto.startswith("100%")
        # Y nombra lo que falta, en lugar de esconderlo tras un promedio.
        assert "brecha" in texto
        assert "cobertura parcial" in texto.lower()
