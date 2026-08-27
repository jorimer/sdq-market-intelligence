"""REGLA ESTRUCTURAL: un producto anual DECLARADO existe y sirve años.

**Por qué estructural.** `annual_companion` es una clave escrita a mano en un manifiesto. Si
apunta a un producto que no existe, o a uno cuyos períodos son fechas y no años, **nada
falla**: el selector simplemente no ofrece la lectura anual, o la ofrece y devuelve un error
al pedirla. Es exactamente la familia «un binding a una serie inexistente no falla», que en
este repo ya dejó 4.280 tests en verde con la serie sin crear.

**Y por qué importa que sirva AÑOS.** El emparejamiento existe para que el selector de un
producto trimestral ofrezca, además de sus cortes, el año. Si el hermano declarado sirviera
fechas, las dos listas serían indistinguibles y volveríamos al defecto que originó todo:
diciembre pareciendo el informe del año.

Alcance declarado: se comprueban los manifiestos de los productos IMPLEMENTADOS. Un producto
del catálogo sin factory registrada no tiene manifiesto que leer y queda fuera — el catálogo
tiene entradas planificadas que todavía no son código.
"""
from __future__ import annotations

import re
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

#: Un año, y nada más. `2025` sí; `2025-12-31` no.
ANIO = re.compile(r"^\d{4}$")


@pytest.fixture()
def db():
    """Sesión con DOS cierres calificados.

    Sembrarla no es decorado: `available_periods` de un producto anual sale de los años que
    tienen su corte de diciembre. Contra una base vacía devuelve `[]`, el bucle de abajo no
    itera y el test pasaría sin haber mirado un solo período — el `@parametrize` vacío de
    siempre, con otro disfraz.
    """
    import app.main  # noqa: F401 — auto-registra los productos reales

    from modules.banking_score.models.models import (Bank, BankType, ModelType,
                                                     RatingResult)
    from shared.database.base import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    # El id lo pone `UUIDMixin`: pasarlo a mano como `uuid.UUID` no lo acepta SQLite.
    banco = Bank(name="Banco de Prueba", bank_type=BankType.banca_multiple, is_active=True)
    s.add(banco)
    s.flush()
    for anio in (2024, 2025):
        s.add(RatingResult(bank_id=banco.id, period_end=date(anio, 12, 31),
                           model_type=ModelType.deterministic, overall_score=70.0))
    s.commit()
    yield s
    s.close()


def _manifiestos(db):
    from shared.products.registry import PRODUCT_CATALOG, get_product
    for entrada in PRODUCT_CATALOG:
        producto = get_product(entrada.sector_key, db)
        if producto is None:
            continue
        yield entrada.sector_key, producto.product_manifest()


def test_el_barrido_encuentra_manifiestos(db):
    """Prueba NEGATIVA. Sin esto, un registro vacío —o un import que dejó de ejecutarse—
    daría cero manifiestos, cero infractores y verde sin haber leído nada."""
    assert len(list(_manifiestos(db))) >= 5


def test_hay_al_menos_un_emparejamiento_declarado(db):
    """La otra mitad de la prueba negativa: si nadie declara `annual_companion`, el test de
    abajo no comprueba NADA y no avisa. Hoy lo declara banca; el día que se retire, este
    test obliga a decidirlo a propósito en vez de perderlo en silencio."""
    declarados = [k for k, m in _manifiestos(db) if m.annual_companion]
    assert declarados, "Ningún producto declara `annual_companion`."


def test_el_producto_anual_declarado_EXISTE_en_el_catalogo(db):
    for clave, manifiesto in _manifiestos(db):
        hermano = manifiesto.annual_companion
        if not hermano:
            continue
        from shared.products.registry import CATALOG_BY_KEY
        assert hermano in CATALOG_BY_KEY, (
            f"'{clave}' declara el producto anual '{hermano}', que no está en el catálogo. "
            "Un emparejamiento a un producto inexistente no falla: hace desaparecer la "
            "lectura anual del selector, sin aviso.")
        from shared.products.registry import get_product
        assert get_product(hermano, db) is not None, (
            f"'{clave}' declara '{hermano}', que está en el catálogo pero no tiene "
            "implementación registrada.")


def test_el_producto_anual_declarado_sirve_AÑOS_y_no_fechas(db):
    for clave, manifiesto in _manifiestos(db):
        hermano = manifiesto.annual_companion
        if not hermano:
            continue
        from shared.products.registry import get_product
        producto = get_product(hermano, db)
        fn = getattr(producto, "available_periods", None)
        assert callable(fn), (
            f"'{hermano}' no expone `available_periods`: el selector no puede ofrecer sus "
            "años.")
        periodos = fn()
        # Que la lista NO esté vacía es parte de la prueba: con una base sin cierres el
        # bucle no iteraría y esto pasaría sin haber mirado ningún período.
        assert periodos, (
            f"'{hermano}' no devolvió ningún período con la base sembrada (2024 y 2025 "
            "cerrados). O la siembra dejó de servirle, o el producto no lee los cierres.")
        for periodo in periodos:
            assert ANIO.match(str(periodo)), (
                f"'{hermano}' sirve el período '{periodo}', que no es un año. El "
                "emparejamiento existe para distinguir el AÑO del CORTE; con fechas de los "
                "dos lados, las dos lecturas se vuelven indistinguibles en pantalla.")


def test_un_producto_NO_es_su_propio_hermano_anual(db):
    """Se apuntaría a sí mismo y el selector duplicaría cada corte. Barato de escribir,
    imposible de diagnosticar desde la pantalla."""
    for clave, manifiesto in _manifiestos(db):
        assert manifiesto.annual_companion != clave, (
            f"'{clave}' se declara a sí mismo como su producto anual.")
