"""La última sección: conclusión y RESPONSABILIDAD — quién responde, con qué versión del
método, con qué estado de validación y desde qué posición frente a la entidad.

**El defecto.** Contra la estructura de diez secciones pedida, la novena —conclusión y
firma— no existía: el informe concluía un valor y nadie lo firmaba (los siete «firma /
certific» de un Deep Dive real eran «afirmar» y «confirmado»). Tres decisiones del dueño
(2026-09-06) la gobiernan: firma INSTITUCIONAL (SDQ Consulting); independencia AFIRMADA salvo
para las entidades declaradas en `settings.VALUACION_ENTIDADES_CON_RELACION`; en insight y
deep dive.

**Todo computado.** Emisión = fecha del snapshot; versión = última entrada del registro de
cambios del eje; validación = `validation_state()`; relación = configuración. Y el registro
de cambios TIENE que tener la entrada del ROE de doce meses (#1141): un cambio que movió
todas las cifras del eje sin entrada en el changelog deja «¿por qué cambió mi cifra?» sin
respuesta.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from datetime import date

import pytest

from modules.valuation.tests.test_el_entorno_llega_al_informe import _db, _por_http
from shared.products.tiers import ProductTier

RAIZ = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture()
def db():
    s = _db()
    yield s
    s.close()


@pytest.mark.parametrize("tier", ["insight", "deep_dive"])
def test_la_seccion_de_CIERRE_llega_por_HTTP_y_es_la_ultima_antes_del_anexo(db, tier) -> None:
    from modules.valuation.products import SECCION_ANEXO_PANEL, SECCION_CIERRE
    cuerpo = _por_http(db, tier)
    assert SECCION_CIERRE in cuerpo["narratives"], f"{tier}: no hay sección de cierre"
    # El framework agrega sus secciones estándar (`std_*`) después de las del producto; lo
    # que se juzga acá es el orden de las del producto.
    orden = [s for s in cuerpo["commercial"]["sections"] if not s.startswith("std_")]
    resto = [s for s in orden if s != SECCION_ANEXO_PANEL]
    assert resto[-1] == SECCION_CIERRE, f"{tier}: el cierre no es la última sección: {orden}"
    if tier == "deep_dive":
        assert orden[-1] == SECCION_ANEXO_PANEL, "el anexo va después del cierre"


def test_el_cierre_trae_EMISION_corte_VERSION_del_metodo_y_estado_de_VALIDACION(db) -> None:
    from modules.valuation.products import SECCION_CIERRE, ValuationProduct
    from shared.doctrine.changelog import cambios
    cierre = _por_http(db)["narratives"][SECCION_CIERRE]
    assert date.today().isoformat() in cierre, "la fecha de emisión no es la del snapshot"
    assert "2025-12-31" in cierre, "no cita el corte"
    ultimo = cambios("valuation")[0]
    assert ultimo["id"] in cierre and ultimo["titulo"] in cierre, (
        "la versión de la metodología no es la última entrada del registro de cambios")
    v = ValuationProduct(db).validation_state()
    assert not v.approved
    assert "No contrastada contra" in cierre
    assert ValuationProduct.ESTADO_BACKTEST.desenlace in cierre
    assert "SDQ Consulting" in cierre and "sin firmante personal" in cierre
    assert "NIIF 13" in cierre


def test_la_conclusion_repite_el_VALOR_del_snapshot_y_no_otro(db) -> None:
    from modules.valuation.products import SECCION_CIERRE, ValuationProduct
    snap = ValuationProduct(db).snapshot(ProductTier.deep_dive, "2025-12-31", scope="aap1")
    va = snap.payload["valor"]
    cierre = _por_http(db)["narratives"][SECCION_CIERRE]
    for v in (va["rango"][0], va["rango"][1], va["patrimonio_libro"]):
        assert f"RD$ {v:,.0f}" in cierre, f"la conclusión no cita {v:,.0f}"
    assert f"{va['pb_implicito'][0]:.2f}×" in cierre


def test_la_INDEPENDENCIA_se_afirma_salvo_para_una_entidad_con_relacion_declarada(db, monkeypatch):
    from modules.valuation.narrativa import FRASE_INDEPENDENCIA, FRASE_RELACION_DECLARADA
    from modules.valuation.products import SECCION_CIERRE
    from shared.config.settings import settings
    cierre = _por_http(db)["narratives"][SECCION_CIERRE]
    assert FRASE_INDEPENDENCIA[:30] in cierre
    assert FRASE_RELACION_DECLARADA[:23] not in cierre
    # La configuración nombra a la entidad (por nombre, sin distinguir mayúsculas): se
    # declara la relación y NO se afirma independencia.
    monkeypatch.setattr(settings, "VALUACION_ENTIDADES_CON_RELACION", "asociación grande, otra")
    con_relacion = _por_http(db)["narratives"][SECCION_CIERRE]
    assert FRASE_RELACION_DECLARADA[:23] in con_relacion, "la relación configurada no se declaró"
    assert FRASE_INDEPENDENCIA[:30] not in con_relacion, "afirma independencia con relación declarada"
    assert "Asociación Grande" in con_relacion
    # Y la otra entidad del tipo sigue independiente.
    otra = _por_http(db, scope="aap2")["narratives"][SECCION_CIERRE]
    assert FRASE_INDEPENDENCIA[:30] in otra


def test_el_bloque_de_cierre_VIAJA_en_el_payload(db) -> None:
    from modules.valuation.products import ValuationProduct
    snap = ValuationProduct(db).snapshot(ProductTier.deep_dive, "2025-12-31", scope="aap1")
    c = snap.payload["cierre"]
    assert c["emitido_el"] == date.today().isoformat() and c["corte"] == "2025-12-31"
    assert c["metodologia"]["id"] and c["validacion"]["aprobada"] is False
    assert c["relacion_declarada"] is None


def test_la_MUESTRA_trae_el_cierre_computado() -> None:
    from modules.valuation.products import SECCION_CIERRE, ValuationProduct
    from shared.doctrine.changelog import cambios
    prod = ValuationProduct()
    narr = asyncio.run(prod.narratives(ProductTier.insight,
                                       prod.sample_snapshot(ProductTier.insight)))
    assert SECCION_CIERRE in narr
    assert cambios("valuation")[0]["id"] in narr[SECCION_CIERRE]


def test_el_registro_de_cambios_tiene_la_entrada_del_ROE_de_doce_meses() -> None:
    """Un cambio que movió TODAS las cifras del eje sin entrada en el changelog deja «¿por qué
    cambió mi cifra?» sin respuesta. La entrada nombra el PR que lo introdujo."""
    from shared.doctrine.changelog import cambios, _prs
    entradas = cambios("valuation")
    assert entradas, "el eje de valuación no tiene ninguna entrada en el registro de cambios"
    assert any(1141 in _prs(c["pr"]) for c in entradas), "falta la entrada del ROE de doce meses (#1141)"


def test_las_frases_del_cierre_son_CONSTANTES_de_modulo() -> None:
    arbol = ast.parse((RAIZ / "modules/valuation/narrativa.py").read_text("utf-8"))
    nombres = {t.id for n in arbol.body if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Name)}
    for c in ("FRASE_INDEPENDENCIA", "FRASE_RELACION_DECLARADA", "FRASE_RESPONSABILIDAD",
              "FRASE_ALCANCE_NORMATIVO"):
        assert c in nombres, f"falta la constante {c}"
