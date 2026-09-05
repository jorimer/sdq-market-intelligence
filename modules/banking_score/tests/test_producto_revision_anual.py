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


def test_el_DEEP_DIVE_agrega_lo_que_exige_el_panel_COMPLETO():
    """Lo que separa al Deep Dive del Insight son las dos lecturas que necesitan el libro de
    las otras noventa y una entidades, no una redacción más larga:

    * `contexto_de_mercado` — «bajó 4 puntos» contra «bajó 4 puntos mientras su tipo subió 1»;
    * `mapa_sectorial` — su mora y su tasa por sector contra el RESTO del sistema.

    Sin ellas los dos niveles serían el mismo documento a dos precios."""
    from modules.banking_score.products_year_review import year_review_manifest

    m = year_review_manifest()
    insight = set(m.levels[ProductTier.insight].sections)
    deep = set(m.levels[ProductTier.deep_dive].sections)
    assert insight < deep
    assert deep - insight == {"contexto_de_mercado", "mapa_sectorial"}


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


# ── Las secciones se generan EN PARALELO ──────────────────────────
#
# Era el único producto del catálogo que hacía `await` dentro del bucle, así que su tiempo de
# ensamblado era la SUMA de sus secciones y no la más lenta. Medido en producción sobre la
# ventana del 25/8 al 1/9: la suma de p90 daba 347,4 s contra un techo de 270 s, y el máximo
# —lo que tarda faneado— 212,3 s. El test estructural que barre los productos vigila la FORMA;
# éste vigila la CONSECUENCIA, que es la que importa y la que un refactor puede perder sin
# tocar el `gather`.

class _MotorLento:
    """Motor de mentira: cada sección tarda `demora` y anota cuántas corrían a la vez."""

    def __init__(self, demora=0.15):
        self.demora = demora
        self.en_vuelo = 0
        self.max_en_vuelo = 0

    async def generate(self, **kw):
        import asyncio

        self.en_vuelo += 1
        self.max_en_vuelo = max(self.max_en_vuelo, self.en_vuelo)
        try:
            await asyncio.sleep(self.demora)
        finally:
            self.en_vuelo -= 1
        return type("R", (), {"text": f"texto de {kw['template']}"})()


def _producto_con_tres_secciones():
    from modules.banking_score.products_year_review import BankingYearReviewProduct

    p = BankingYearReviewProduct(None)
    payload = {"mapa_sectorial": {"hay": True}, "revision": {}}
    snap = type("S", (), {"period": "2025", "payload": payload,
                          "entity_name": "Entidad de Prueba"})()
    return p, snap


def test_las_tres_secciones_corren_A_LA_VEZ(monkeypatch):
    """Tres secciones se generan SOLAPADAS, así que el informe tarda la más lenta y no la suma.

    La propiedad se mide con el CONTADOR DE SOLAPAMIENTO, no con el reloj de pared. Tres
    corrutinas simultáneamente dentro de `generate` solo pueden estar ahí si se agendaron a
    la vez; en serie el máximo sería 1. Es una prueba directa, no un indicio.

    **Acá hubo un `assert tardanza < motor.demora * 2` y se sacó, medido.** Falló en CI con
    0,60 s mientras `max_en_vuelo == 3` pasaba en la misma corrida: las secciones SÍ habían
    corrido en paralelo y lo lento era el runner. Y no se puede reparar subiendo el umbral:
    una corrida secuencial daría >= 0,45 s, o sea que con 0,60 s observados **no existe un
    umbral que separe «lento» de «secuencial»**. Esa aserción no medía el código, medía la
    máquina, y su único efecto era volver rojo un PR que no había tocado nada de esto.
    """
    import asyncio

    from shared.narrative import claude_engine

    motor = _MotorLento()
    monkeypatch.setattr(claude_engine, "narrative_engine", motor)
    p, snap = _producto_con_tres_secciones()

    out = asyncio.run(p.narratives(ProductTier.deep_dive, snap))

    assert len(out) == 3, f"se esperaban tres secciones, llegaron {sorted(out)}"
    assert motor.max_en_vuelo == 3, (
        f"solo {motor.max_en_vuelo} sección(es) a la vez: se volvieron a generar de a una, y "
        "el tiempo del informe vuelve a ser la SUMA en vez de la más lenta")
    assert motor.en_vuelo == 0, "quedó una generación colgada"


def test_el_ORDEN_de_las_secciones_se_conserva(monkeypatch):
    """`gather` devuelve en el orden en que se pidió, no en el que terminó — pero eso hay que
    comprobarlo: el render arma el documento con estas claves y una sección fuera de lugar
    saldría en la sección equivocada del PDF."""
    import asyncio

    from shared.narrative import claude_engine

    monkeypatch.setattr(claude_engine, "narrative_engine", _MotorLento(demora=0.01))
    p, snap = _producto_con_tres_secciones()
    out = asyncio.run(p.narratives(ProductTier.deep_dive, snap))
    esperado = list(p.product_manifest().require_level(ProductTier.deep_dive).sections)
    assert list(out) == esperado


def test_una_seccion_SIN_dato_se_sigue_omitiendo(monkeypatch):
    """El fan-out no puede haberse llevado puesta la regla de «sin dato no hay sección»: el
    mapa sectorial se omite cuando el payload no lo trae, porque el cubo empieza en 2021."""
    import asyncio

    from shared.narrative import claude_engine

    motor = _MotorLento(demora=0.01)
    monkeypatch.setattr(claude_engine, "narrative_engine", motor)
    p, _snap = _producto_con_tres_secciones()
    sin_mapa = type("S", (), {"period": "2019", "payload": {"revision": {}},
                              "entity_name": "Entidad de Prueba"})()
    out = asyncio.run(p.narratives(ProductTier.deep_dive, sin_mapa))
    assert "mapa_sectorial" not in out
    assert motor.max_en_vuelo == 2, "se pidió una sección que no tenía dato"
