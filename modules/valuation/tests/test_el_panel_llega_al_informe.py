"""El panel de transacciones LLEGA al informe: tabla, resumen, posición del rango y anexo.

**El defecto.** `panel/transacciones.py` computa el panel entero —comparables, mediana, mínimo
y máximo, el gate, las vías abiertas y los descartes— y el informe no lo pedía: la metodología
y las limitaciones decían que «el panel dice a cuánto sobre libro se ha pagado» y no mostraban
ni tabla, ni rango, ni conteo. El único llamador fuera del panel era `validation_state()`.

Familia «servir el dato no alcanza: hay que pedirlo». Cada eje son DOS trabajos —el motor y
la plantilla— y acá faltaba el segundo.

**Por qué estos tests entran por el ENSAMBLADOR y por HTTP y no por la función de prosa.**
Un guard que construye el objeto intermedio a mano declara cumplida la precondición que está
probando: esta misma semana uno así dejó pasar el defecto real. Acá el informe se pide como
lo pide el cliente —`assemble_product_content`, `assemble_product_report`,
`GET /api/v1/products/valuation/deep_dive/report`— y se lee lo que sale.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import date
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.auth.models  # noqa: F401
import shared.products.models  # noqa: F401 — la caché de informes, que el ensamblador consulta
from modules.banking_score.models.models import Bank, BankingData, BankType, DataSource
from modules.macro_monitor.models.models import MacroSeries
from modules.valuation.engine import crecimiento as cr
from modules.valuation.engine.cost_of_capital import SERIE_RF
from modules.valuation.panel import transacciones as tx
from modules.valuation.products import (
    _SECTION_TITLES,
    SECCION_ANEXO_PANEL,
    SECCION_CONTRASTE,
    SECCION_FUENTES,
    SECCION_METODOLOGIA,
    ValuationProduct,
    valuation_manifest,
)
from shared.database.base import Base
from shared.products.assembler import assemble_product_content, assemble_product_report
from shared.products.tiers import ProductTier

RAIZ = pathlib.Path(__file__).resolve().parents[3]

CURVA = [("2025-01", 11.96), ("2025-04", 9.71), ("2025-07", 9.61), ("2025-10", 9.93),
         ("2026-01", 9.94), ("2026-03", 9.61), ("2026-05", 10.02), ("2026-07", 9.78)]


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    for ident, nombre, patr in (("aap1", "Asociación Grande", 30_000_000_000.0),
                                ("aap2", "Asociación Chica", 10_000_000_000.0)):
        s.add(Bank(id=ident, name=nombre, bank_type=BankType.aap))
        for j, anio in enumerate((2022, 2023, 2024, 2025)):
            s.add(BankingData(bank_id=ident, period_end=date(anio, 12, 31),
                              patrimonio_tecnico=patr * (1.05 ** j),
                              utilidad_neta=patr * 0.10, source=DataSource.sib_api))
    for p, v in CURVA:
        s.add(MacroSeries(series_code=SERIE_RF, period=p, value=v))
    for i in range(29):
        s.add(MacroSeries(series_code=cr.SERIE_PIB_NOMINAL,
                          period=f"{2019 + i // 4}-Q{i % 4 + 1}", value=9.03))
    s.commit()
    yield s
    s.close()


def _contenido(db, tier=ProductTier.deep_dive):
    """El informe como lo arma la ruta: snapshot + narrativas + orden, por el ensamblador."""
    return asyncio.run(assemble_product_content(
        ValuationProduct(db), tier, period="2025-12-31", scope="aap1"))


def _bloques(seccion: str) -> Dict[str, str]:
    """La sección se parte por sus subtítulos `###`: cada bloque se juzga por separado, y
    así «el caso de valor razonable NO está en la tabla de comparables» se puede afirmar
    aunque sí esté, marcado, unas líneas más abajo."""
    bloques: Dict[str, str] = {}
    actual = "_intro"
    for linea in seccion.splitlines():
        if linea.startswith("### "):
            actual = linea[4:].strip()
            bloques[actual] = ""
            continue
        bloques[actual] = bloques.get(actual, "") + linea + "\n"
    return bloques


# ── La sección existe y trae lo que el panel computa ─────────────────────────────


@pytest.mark.parametrize("tier", [ProductTier.insight, ProductTier.deep_dive])
def test_la_seccion_de_contraste_LLEGA_por_el_ensamblador(db, tier) -> None:
    c = _contenido(db, tier)
    assert SECCION_CONTRASTE in c.narratives, (
        f"{tier.value}: el panel se computa y el informe no lo pide — no hay sección")
    assert SECCION_CONTRASTE in c.section_order, (
        "la sección tiene texto y no entra al orden: la app no la va a dibujar")
    assert len(c.narratives[SECCION_CONTRASTE]) > 800


def test_la_tabla_trae_a_los_NUEVE_comparables_y_a_NINGUNO_de_valor_razonable(db) -> None:
    """Solo se ordena lo comparable: base contable en la tabla y el resumen; los de NIIF 3
    aparte y marcados. Un múltiplo sobre valor razonable no es un P/B."""
    from modules.valuation.narrativa import (
        SUBTITULO_COMPARABLES, SUBTITULO_OTRA_BASE)
    seccion = _contenido(db).narratives[SECCION_CONTRASTE]
    bloques = _bloques(seccion)
    assert SUBTITULO_COMPARABLES in bloques and SUBTITULO_OTRA_BASE in bloques, list(bloques)
    tabla, otra_base = bloques[SUBTITULO_COMPARABLES], bloques[SUBTITULO_OTRA_BASE]
    assert "| Año | Comprador | Adquirida | País | P/B | Base | Corte del libro |" in tabla
    comparables = [t for t in tx.PANEL if t.comparable]
    otros = [t for t in tx.PANEL if t.verificable and not t.comparable]
    # Los conteos salen del PANEL, no se fijan a mano: el panel crece (#1134 sumó el quinto
    # caso sobre valor razonable mientras esto se escribía) y un 4 fijo habría roto el test
    # por la razón equivocada. Lo que se exige es que haya de los DOS lados.
    assert len(comparables) >= tx.MINIMO_DE_CASOS and otros, "el panel cambió de forma"
    for t in comparables:
        assert t.adquirida[:18] in tabla, f"falta el comparable {t.adquirida[:40]}"
        assert f"{t.pb_recomputado:.2f}×" in tabla, (
            f"{t.adquirida[:30]}: el múltiplo publicado no es el recomputado de sus insumos")
    for t in otros:
        assert t.adquirida[:18] not in tabla, (
            f"{t.adquirida[:40]} está sobre VALOR RAZONABLE y entró a la tabla de comparables")
        assert t.adquirida[:18] in otra_base, (
            f"{t.adquirida[:40]} no aparece ni marcado aparte: desapareció sin aviso")
    # Los de otra base van marcados como lo que son, no como P/B.
    assert "valor razonable" in otra_base.lower()


def test_la_mediana_el_minimo_y_el_maximo_son_los_de_resumen(db) -> None:
    """Computados en el panel y COPIADOS por la plantilla — nunca transcritos a mano."""
    r = tx.resumen()
    assert r is not None
    seccion = _contenido(db).narratives[SECCION_CONTRASTE]
    for nombre, valor in (("mediana", r.mediana), ("mínimo", r.minimo), ("máximo", r.maximo)):
        assert f"{valor:.2f}×" in seccion, f"el {nombre} de `resumen()` no llegó al informe"
    assert f"{r.n} comparables" in seccion or f"{r.n} operaciones" in seccion


def test_la_posicion_del_rango_se_COMPUTA_y_coincide_con_el_dato(db) -> None:
    """La relación —por debajo, por encima, solapa— se calcula en código sobre el mismo
    snapshot que se publica. La prosa tiene que decir lo que el dato dice, y NO lo contrario."""
    from modules.valuation import narrativa as n
    c = _contenido(db)
    va = c.snapshot.payload["valor"]
    pb_bajo, pb_alto = va["pb_implicito"]
    r = tx.resumen()
    assert r is not None
    seccion = c.narratives[SECCION_CONTRASTE]
    if pb_alto < r.minimo:
        assert n.FRASE_RANGO_POR_DEBAJO in seccion and n.FRASE_RANGO_POR_ENCIMA not in seccion
    elif pb_bajo > r.maximo:
        assert n.FRASE_RANGO_POR_ENCIMA in seccion and n.FRASE_RANGO_POR_DEBAJO not in seccion
    else:
        assert n.FRASE_RANGO_SOLAPA in seccion
        assert n.FRASE_RANGO_POR_DEBAJO not in seccion
        assert n.FRASE_RANGO_POR_ENCIMA not in seccion
    # Y las cifras que sostienen la relación viajan con ella.
    assert f"{pb_bajo:.2f}×" in seccion and f"{pb_alto:.2f}×" in seccion


def test_la_posicion_distingue_los_TRES_casos() -> None:
    """El contraejemplo de la función: sin esto, una prosa que dijera siempre «solapa»
    pasaría el test de la ruta si la fixture cae en el medio del panel."""
    from modules.valuation import narrativa as n
    r = tx.resumen()
    assert r is not None and r.minimo < r.maximo
    abajo = n.posicion_frente_al_panel(r.minimo * 0.5, r.minimo * 0.9, r)
    arriba = n.posicion_frente_al_panel(r.maximo * 1.1, r.maximo * 1.5, r)
    medio = n.posicion_frente_al_panel(r.mediana * 0.9, r.mediana * 1.1, r)
    assert abajo.por_debajo and not abajo.por_encima and not abajo.solapa
    assert arriba.por_encima and not arriba.por_debajo and not arriba.solapa
    assert medio.solapa and medio.mediana_dentro_del_rango
    # Y la prosa copia la relación computada, en las tres direcciones.
    assert n.FRASE_RANGO_POR_DEBAJO in n.prosa_de_la_posicion(abajo, r)
    assert n.FRASE_RANGO_POR_ENCIMA in n.prosa_de_la_posicion(arriba, r)
    assert n.FRASE_RANGO_SOLAPA in n.prosa_de_la_posicion(medio, r)


def test_el_contraste_NO_se_presenta_como_validacion_del_modelo(db) -> None:
    """La distinción más cara del eje: un panel abierto es evidencia de MERCADO, no de que
    este modelo acierte. La sección lo dice con el conteo que computa el panel."""
    c = tx.contraste_del_modelo()
    seccion = _contenido(db).narratives[SECCION_CONTRASTE]
    assert "no contrasta el modelo" in seccion.lower() or "no valida el modelo" in seccion.lower()
    assert f"{c.n_valuables} de {c.n_comparables}" in seccion or \
        f"{c.n_valuables} de los {c.n_comparables}" in seccion
    assert "no se usa para producir el valor" in seccion.lower() or \
        "no produce el valor" in seccion.lower()


def test_con_el_gate_CERRADO_la_seccion_declara_el_motivo_y_no_arma_tabla() -> None:
    """El gate se consulta antes, no después. Con un panel corto la sección no puede
    publicar una tabla de tres casos como si fuera un mercado: declara la brecha."""
    from modules.valuation import narrativa as n
    from modules.valuation.products import _lectura_desde_payload, _SAMPLE_PAYLOAD
    from shared.products.contract import ProductSnapshot
    lec = _lectura_desde_payload(ProductSnapshot(
        tier=ProductTier.deep_dive, period="2025-12-31", payload=_SAMPLE_PAYLOAD))
    chico = [t for t in tx.PANEL if t.comparable][:3]
    texto = n.contraste_de_mercado(lec, panel=chico, con_anexo=False)
    assert "| Año |" not in texto, "armó la tabla con el gate cerrado"
    assert "gate exige" in texto or "queda cerrada" in texto


# ── El anexo: vías abiertas y descartes ───────────────────────────────────────────


def test_el_DEEP_DIVE_trae_el_anexo_con_TODAS_las_vias_y_descartes(db) -> None:
    """Un panel chico sin explicación se lee como falta de trabajo; el anexo es el
    resultado del trabajo. Se listan todas, con su motivo, y no una selección."""
    c = _contenido(db, ProductTier.deep_dive)
    assert SECCION_ANEXO_PANEL in c.narratives and SECCION_ANEXO_PANEL in c.section_order
    anexo = c.narratives[SECCION_ANEXO_PANEL]
    for nombre, _ in tx.VIAS_ABIERTAS:
        assert nombre[:30] in anexo, f"vía abierta ausente del anexo: {nombre[:50]}"
    for nombre, motivo in tx.DESCARTADAS:
        assert nombre[:30] in anexo, f"descarte ausente del anexo: {nombre[:50]}"
        assert motivo[:40] in anexo, f"descarte sin su motivo: {nombre[:50]}"
    assert tx.DISCREPANCIA_RFHL[:40] in anexo
    # Y los caveats de cada comparable viajan con su caso: lo que el caso NO permite
    # afirmar no se pierde al pasar a una tabla de siete columnas.
    for t in tx.PANEL:
        if t.comparable:
            assert t.caveats[0][:40] in anexo, f"{t.adquirida[:30]}: sus caveats no llegaron"


def test_el_INSIGHT_no_trae_el_anexo_pero_si_lo_nombra(db) -> None:
    c = _contenido(db, ProductTier.insight)
    assert SECCION_ANEXO_PANEL not in c.narratives
    seccion = c.narratives[SECCION_CONTRASTE]
    assert f"{len(tx.DESCARTADAS)} operaciones" in seccion or \
        f"{len(tx.DESCARTADAS)} descart" in seccion, (
        "el insight no dice cuántas operaciones se relevaron y descartaron")


# ── Las superficies: manifiesto, títulos, PDF, muestra, UI ───────────────────────


def test_las_secciones_nuevas_estan_en_el_manifiesto_y_tienen_titulo() -> None:
    m = valuation_manifest()
    for tier in (ProductTier.insight, ProductTier.deep_dive):
        assert SECCION_CONTRASTE in m.require_level(tier).sections, tier.value
    assert SECCION_ANEXO_PANEL in m.require_level(ProductTier.deep_dive).sections
    for tier, nivel in m.levels.items():
        for sec in nivel.sections:
            assert sec in _SECTION_TITLES, f"{tier.value}: «{sec}» sin título en el PDF"


def test_el_PDF_real_recibe_la_seccion_y_su_titulo(db, monkeypatch) -> None:
    """Por la ruta de descarga —`assemble_product_report`—, espiando lo que el producto le
    PASA al renderizador: si la sección no viaja ahí, el PDF no la puede imprimir."""
    import modules.valuation.products as mod
    capturado: Dict[str, Any] = {}
    real = mod.render_product_pdf

    def espia(**kw: Any) -> str:
        capturado.update(kw)
        return real(**kw)

    monkeypatch.setattr(mod, "render_product_pdf", espia)
    ruta = asyncio.run(assemble_product_report(
        ValuationProduct(db), ProductTier.deep_dive, period="2025-12-31", scope="aap1",
        output_dir="/tmp"))
    assert ruta.endswith(".pdf")
    assert SECCION_CONTRASTE in capturado["narratives"]
    assert SECCION_ANEXO_PANEL in capturado["narratives"]
    assert SECCION_CONTRASTE in capturado["section_titles"]


def test_la_metodologia_y_las_fuentes_APUNTAN_a_la_seccion(db) -> None:
    """La prosa vieja decía que el panel «sirve para ver si el rango es razonable» y no
    mostraba nada. Ahora remite a la sección, y el panel entra a la tabla de procedencia."""
    narr = _contenido(db).narratives
    assert _SECTION_TITLES[SECCION_CONTRASTE].split(" ·")[0] in narr[SECCION_METODOLOGIA]
    assert "transacciones" in narr[SECCION_FUENTES].lower()
    assert "relevamiento propio" in narr[SECCION_FUENTES].lower()


def test_la_MUESTRA_sale_del_MISMO_constructor_que_el_informe_real(db, monkeypatch) -> None:
    """Una muestra escrita a mano tapó un defecto de unidades en otro eje esta semana. La
    de acá no puede: si el constructor cambia, cambian las dos."""
    import modules.valuation.products as mod

    def centinela(lec, **_kw):
        return {s: f"CENTINELA {s}" for s in _SECTION_TITLES}

    monkeypatch.setattr(mod, "_secciones_computadas", centinela)
    prod = ValuationProduct(db)
    muestra = prod.sample_narratives(ProductTier.deep_dive)
    assert muestra[SECCION_CONTRASTE].startswith(f"CENTINELA {SECCION_CONTRASTE}")
    snap = prod.snapshot(ProductTier.deep_dive, "2025-12-31", scope="aap1")
    real = asyncio.run(prod.narratives(ProductTier.deep_dive, snap))
    assert real[SECCION_CONTRASTE] == f"CENTINELA {SECCION_CONTRASTE}"


def test_la_muestra_trae_el_panel_REAL_y_el_aviso_de_ilustrativo() -> None:
    """La entidad de la muestra es ficticia; el panel de transacciones NO lo es, y la
    muestra tiene que enseñarlo tal cual. Lo ilustrativo es la entidad, no el mercado."""
    from shared.products.assembler import assemble_sample_report
    prod = ValuationProduct(None)
    muestra = prod.sample_narratives(ProductTier.deep_dive)
    assert SECCION_CONTRASTE in muestra and SECCION_ANEXO_PANEL in muestra
    r = tx.resumen()
    assert r is not None
    assert f"{r.mediana:.2f}×" in muestra[SECCION_CONTRASTE]
    assert "ilustrativ" in " ".join(muestra.values()).lower()
    ruta = asyncio.run(assemble_sample_report(prod, ProductTier.insight, output_dir="/tmp"))
    assert ruta.endswith(".pdf")


def test_la_seccion_llega_por_HTTP(db) -> None:
    """La ruta que el cliente usa. `require_product_access` se sustituye por una decisión
    permitida: acá se prueba el ensamblado, no el cobro."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from shared.database.session import get_db
    from shared.products.access import AccessDecision, AccessOutcome, AccessTier
    from shared.products.access import require_product_access
    from shared.products.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/products")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_product_access] = lambda: AccessDecision(
        outcome=AccessOutcome.allowed, sector_key="valuation", tier=ProductTier.deep_dive,
        required_tier=AccessTier.enterprise, user_tier=AccessTier.enterprise)
    r = TestClient(app).get("/api/v1/products/valuation/deep_dive/report",
                            params={"period": "2025-12-31", "scope": "aap1"})
    assert r.status_code == 200, r.text[:300]
    cuerpo = r.json()
    assert SECCION_CONTRASTE in cuerpo["narratives"]
    assert SECCION_CONTRASTE in cuerpo["commercial"]["sections"]
    assert SECCION_ANEXO_PANEL in cuerpo["commercial"]["sections"]


@pytest.mark.parametrize("lang", ["es", "en", "fr"])
def test_la_UI_tiene_etiqueta_para_TODAS_las_secciones_de_valuacion(lang) -> None:
    """La app rotula cada sección con `platform.catalog.section.<clave>` y, sin entrada,
    cae a la clave con espacios: «spread roe ke». Un tipo nuevo se registra en TODAS sus
    superficies o desaparece — y la UI es una de ellas."""
    d = json.loads((RAIZ / "frontend/src/shared/i18n" / f"{lang}.json").read_text("utf-8"))
    etiquetas = d["platform"]["catalog"]["section"]
    faltan = sorted({s for nivel in valuation_manifest().levels.values()
                     for s in nivel.sections if s not in etiquetas})
    assert faltan == [], f"{lang}: secciones de valuación sin etiqueta en la UI: {faltan}"


# ── La huella de la caché ─────────────────────────────────────────────────────────


def test_la_huella_de_contexto_cubre_la_prosa_y_el_panel() -> None:
    """`ProductReportCache` no tiene TTL. El ensamblador busca `AI_CONTEXT_FILES` en el
    módulo del PRODUCTO, y valuación lo declaraba en `ai_context.py` sin exponerlo en
    `products.py`: la huella era solo `ai_context.py`, así que un arreglo de la prosa o del
    panel desplegado a producción no invalidaba ningún informe ya generado — esta sección
    nueva habría sido invisible en todos ellos."""
    import modules.valuation.products as mod
    from modules.valuation import ai_context
    from shared.products.assembler import _contexto_ia_version, ruta_de_contexto

    assert mod.AI_CONTEXT_FILES is ai_context.AI_CONTEXT_FILES, "dos listas divergen"
    for rel in ("narrativa.py", "panel/transacciones.py", "products.py"):
        assert rel in mod.AI_CONTEXT_FILES, f"{rel} fuera de la huella"
    faltan = [f for f in mod.AI_CONTEXT_FILES
              if not ruta_de_contexto(f, "valuation").is_file()]
    assert faltan == [], f"declarados y ausentes: {faltan}"
    huella = _contexto_ia_version("modules.valuation.products")
    assert huella
    # Y la prueba de que el archivo PARTICIPA: sin él, la huella es otra.
    sin_panel = tuple(f for f in mod.AI_CONTEXT_FILES if f != "panel/transacciones.py")
    original = mod.AI_CONTEXT_FILES
    try:
        mod.AI_CONTEXT_FILES = sin_panel  # type: ignore[assignment]
        assert _contexto_ia_version("modules.valuation.products") != huella
    finally:
        mod.AI_CONTEXT_FILES = original
