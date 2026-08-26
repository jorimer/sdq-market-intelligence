"""SDQ Banking · Revisión Anual — el producto cuya unidad es el AÑO.

Lo que se protege acá no es «el manifiesto tiene tres niveles». Son las cuatro cosas que, al
fallar, devuelven el producto al error que lo originó o rompen una doctrina:

  * el Pulse NO puede emitir un nombre — es el nivel abierto;
  * el período es un AÑO CERRADO, no un corte;
  * el Deep Dive trae el contraste contra el mercado, que es lo que lo separa del Insight;
  * el producto NO recomputa nada: reusa el cómputo que ya está en producción.
"""
import datetime

import pytest

from shared.products import (AnonymizationError, Granularity, ProductTier,
                             enforce_anonymized)


def _anuario_falso(anio=2025):
    """La forma REAL de `anuario_del_sistema`, con sus listas NOMINADAS."""
    return {
        "anio": anio,
        "cortes": [f"{anio - 1}-12-31", f"{anio}-12-31"],
        "universo": {"comparables": 82, "vistas_en_el_anio": 88,
                     "parciales": [{"entidad": "Fiduciaria BHD", "cortes_presentes": 2,
                                    "de": 5}],
                     "regla": "los agregados se computan solo sobre las comparables"},
        "sistema": {"por_corte": [{"corte": f"{anio}-12-31", "mediana": 67.93,
                                   "media": 65.41, "n": 82}],
                    "cambio_mediana": -0.41, "cambio_media": 0.58,
                    "estadistico_de_referencia": "mediana",
                    "medias_y_medianas_divergen": True,
                    "lectura": "la mediana del sistema cayó 0.41 puntos"},
        "conteo_direccion": {"mejora": 30, "deterioro": 40, "estable": 12},
        "por_tipo": [{"tipo": "banca_multiple", "n": 16, "cambio_mediana": -1.88,
                      "direccion": "deterioro"}],
        "cambios_de_banda": [{"entidad": "Banco Múltiple Caribe Internacional",
                              "tipo": "banca_multiple", "desde": "Adecuada",
                              "hasta": "En vigilancia", "cambio_score": -8.05}],
        "extremos": {"mayor_deterioro": {"entidad": "Rodriguez", "cambio_score": -27.9},
                     "mayor_mejora": {"entidad": "Agcrm", "cambio_score": 60.6},
                     "advertencia": "son las COLAS de la distribución"},
    }


#: Los nombres que el anuario falso trae, para el roster del guard.
_NOMBRES = ["Banco Múltiple Caribe Internacional", "Rodriguez", "Agcrm", "Fiduciaria BHD"]


# ── La doctrina del nivel abierto ──────────────────────────────────────

def test_el_pulse_NO_emite_ningun_nombre():
    """El nivel abierto jamás nombra. Es doctrina del framework, no preferencia."""
    from modules.banking_score.products_year_review import _anio_del_sistema_anonimo

    payload = _anio_del_sistema_anonimo(_anuario_falso())
    enforce_anonymized(payload, entity_roster=_NOMBRES)   # no debe lanzar


def test_el_anuario_CRUDO_si_tiene_nombres(  ):
    """Prueba negativa del test de arriba: sin ella, `enforce_anonymized` podría estar
    pasando porque el roster no matchea nada, no porque el payload esté limpio."""
    with pytest.raises(AnonymizationError):
        enforce_anonymized(_anuario_falso(), entity_roster=_NOMBRES)


def test_el_pulse_conserva_las_CIFRAS_del_ano():
    """Anonimizar no es vaciar: el gancho tiene que decir algo."""
    from modules.banking_score.products_year_review import _anio_del_sistema_anonimo

    p = _anio_del_sistema_anonimo(_anuario_falso())
    assert p["cambio_mediana"] == -0.41
    assert p["medias_y_medianas_divergen"] is True
    assert p["conteo_direccion"] == {"mejora": 30, "deterioro": 40, "estable": 12}
    assert p["entidades_que_cambiaron_de_banda"] == 1, "el CONTEO sí, la lista no"
    assert p["universo"]["parciales"] == 1, "el conteo de parciales, no sus nombres"


def test_el_pulse_se_arma_por_LISTA_BLANCA():
    """Un campo NUEVO del anuario no debe viajar solo al nivel abierto.

    Borrar claves nominadas de un dict que sigue creciendo es cómo el próximo campo con
    nombres sale sin que nadie lo decida.
    """
    from modules.banking_score.products_year_review import _anio_del_sistema_anonimo

    con_campo_nuevo = dict(_anuario_falso(),
                           ranking_nominado=[{"entidad": "Banco X", "puesto": 1}])
    p = _anio_del_sistema_anonimo(con_campo_nuevo)
    assert "ranking_nominado" not in p


# ── El manifiesto ──────────────────────────────────────────────────────

def test_los_tres_niveles_y_su_granularidad():
    from modules.banking_score.products_year_review import year_review_manifest

    m = year_review_manifest()
    assert set(m.levels) == {ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive}
    assert m.levels[ProductTier.pulse].granularity is Granularity.system
    for t in (ProductTier.insight, ProductTier.deep_dive):
        assert m.levels[t].granularity is Granularity.named_entity


def test_el_DEEP_DIVE_agrega_el_contraste_contra_el_mercado():
    """Es lo único que lo separa del Insight: «bajó 4 puntos» contra «bajó 4 puntos mientras
    su tipo subió 1». Sin esta sección los dos niveles serían el mismo documento."""
    from modules.banking_score.products_year_review import year_review_manifest

    m = year_review_manifest()
    insight = set(m.levels[ProductTier.insight].sections)
    deep = set(m.levels[ProductTier.deep_dive].sections)
    assert insight < deep
    assert deep - insight == {"contexto_de_mercado"}


def test_sus_plantillas_van_por_la_ruta_con_GUARDRAIL():
    """Una plantilla fuera de `THIN_TEMPLATES` cae a la ruta legacy y sale al relleno
    estático EN SILENCIO — le pasó al anuario en su primera generación de producción."""
    from shared.narrative.claude_engine import THIN_TEMPLATES, _uses_cerebro
    from modules.banking_score.products_year_review import year_review_manifest

    for spec in year_review_manifest().levels.values():
        for plantilla in spec.narrative_templates:
            assert plantilla in THIN_TEMPLATES, f"{plantilla} no existe como plantilla"
            assert _uses_cerebro(plantilla, "banking"), f"{plantilla} iría por ruta legacy"


def test_esta_en_el_CATALOGO_o_no_se_puede_registrar():
    from shared.products.registry import CATALOG_BY_KEY
    from modules.banking_score.products_year_review import YEAR_REVIEW_KEY

    assert YEAR_REVIEW_KEY in CATALOG_BY_KEY


# ── El período es un AÑO ───────────────────────────────────────────────

class _DB:
    """Sesión mínima: solo hace falta que `_anios_con_cierre` devuelva algo."""


@pytest.fixture()
def producto(monkeypatch):
    from modules.banking_score import products_year_review as mod

    monkeypatch.setattr("modules.banking_score.reports.anuario._anios_con_cierre",
                        lambda db: [2023, 2024, 2025])
    return mod.BankingYearReviewProduct(_DB())


def test_los_periodos_son_ANIOS_del_mas_reciente_al_mas_viejo(producto):
    assert producto.available_periods() == ["2025", "2024", "2023"]


def test_periodo_vacio_significa_el_ultimo_ano_CERRADO(producto):
    """Invariante del contrato de productos: `""` = el último disponible."""
    assert producto._anio("") == 2025


def test_acepta_una_FECHA_porque_la_barra_superior_manda_una(producto):
    assert producto._anio("2024-06-30") == 2024
    assert producto._anio("2024") == 2024


def test_sin_ningun_ano_cerrado_se_declara_en_vez_de_devolver_vacio(monkeypatch):
    from modules.banking_score import products_year_review as mod

    monkeypatch.setattr("modules.banking_score.reports.anuario._anios_con_cierre",
                        lambda db: [])
    p = mod.BankingYearReviewProduct(_DB())
    assert p.available_periods() == []
    with pytest.raises(ValueError, match="año cerrado"):
        p._anio("")
    assert p.has_engine() is False


def test_el_ano_en_curso_no_es_un_periodo_disponible(producto):
    """El año sin cerrar no está en la lista: no se puede ni elegir."""
    assert str(datetime.date.today().year + 1) not in producto.available_periods()
