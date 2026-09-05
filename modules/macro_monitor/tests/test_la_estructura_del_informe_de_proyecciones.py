"""El informe abría con dos páginas de tablas que la prosa vuelve a publicar, y sin un gráfico.

Medido sobre `SDQ_Proyecciones_Deep-Dive_Sistema_2026-09-05.pdf`:

* **Las tablas de portada son duplicados EMPOBRECIDOS.** `render()` arma `tables` con las
  mismas filas que §2 y §4 ya publican en Markdown, y las de portada pierden el encabezado:
  la lista por comprensión emite solo filas de dato. Tras el arreglo de la lectura sectorial
  la de portada es además un SUBCONJUNTO — 4 columnas contra 5.

  El dueño ya decidió sobre este patrón para otro producto, y está escrito en el docstring de
  `render_product_pdf`: «un informe que abre con páginas de tablas antes de una sola frase se
  lee como un anexo, no como un informe (pedido del dueño sobre el de brand_intel)». Acá
  `tables_last` no es la cura: la cura es no publicarlas dos veces.

* **Siete puntos de trayectoria y ningún gráfico.** El gráfico exigía `len(items) >= 2` sobre
  las proyecciones VIGENTES —hoy hay una— e ignoraba los seis ESCENARIOS (2026-Q4 → 2028-Q1),
  que son puntos de la misma trayectoria y que el propio informe publica en §3.

  Al graficarlos hay que conservar la distinción que §3 existe para sostener: un escenario no
  es un pronóstico y no lleva track record. Van rotulados, nunca fundidos con los vigentes.

* **Dos secciones se llamaban «Metodología»** — §6 «Metodología y límites» del producto y §8
  «Metodología y fuentes» del framework.

* **Faltaban el resumen ejecutivo y el propósito y alcance** del estándar que el eje de
  valuación sí recibió: las dos secciones que un lector usa para decidir si sigue leyendo.
"""
import pytest

from shared.products import ProductTier

SECTOR = "macro_forecast"


def _render_args(tier=ProductTier.deep_dive, **payload_over):
    """Los argumentos con que el producto llama al renderer, sin escribir un PDF.

    Se espía la llamada en vez de leer el PDF a propósito: leerlo pediría una dependencia
    nueva solo para el test, y lo que se quiere fijar es lo que el producto DECIDE publicar.
    """
    import asyncio
    from unittest.mock import patch

    import app.main  # noqa: F401
    from modules.macro_monitor import products_forecast as pf
    from shared.products import ProductSnapshot

    payload = dict(pf._SAMPLE_PAYLOAD)
    payload.update(payload_over)
    prod = pf.MacroForecastProduct(db=None)
    snap = ProductSnapshot(tier=tier, period="2026-08-20", payload=payload, entity_name=None)
    narr = prod.sample_narratives(tier)

    capturado = {}

    def _espia(**kw):
        capturado.update(kw)
        return "/tmp/no-se-escribe.pdf"

    with patch.object(pf, "render_product_pdf", _espia):
        asyncio.run(prod.render(tier, snap, narr, sample=True))
    assert capturado, "el producto no llamó al renderer"
    return capturado


# ── las tablas ──────────────────────────────────────────────────────────────────────

def test_la_portada_no_repite_las_tablas_que_la_prosa_ya_publica():
    """Publicarlas dos veces no es un detalle de maqueta: la de portada va SIN encabezado.

    Un lector que abre el informe se encuentra 18 filas de números sin nombres de columna
    antes de la primera frase, y después las mismas 18 con encabezado dentro de §4.
    """
    args = _render_args()
    titulos = [t for t, _filas in (args.get("tables") or [])]
    assert not titulos, (
        f"la portada publica {titulos}, que §2 y §4 ya publican con encabezado y con más "
        "columnas")


def test_si_alguna_tabla_va_a_portada_LLEVA_encabezado():
    """El guard de la forma, no del contenido: si mañana vuelve una tabla, que no vuelva rota.

    La regla es sobre la PRIMERA fila, que es donde estaba el defecto: la lista por
    comprensión emitía solo filas de dato y el encabezado no existía en ninguna parte.
    """
    args = _render_args()
    for titulo, filas in (args.get("tables") or []):
        assert filas, f"la tabla «{titulo}» va vacía"
        cabecera = filas[0]
        assert all(not _parece_dato(str(c)) for c in cabecera), (
            f"la primera fila de «{titulo}» es dato, no encabezado: {cabecera}")


def _parece_dato(celda: str) -> bool:
    """Una celda que empieza con dígito, signo o coma decimal es un valor, no un rótulo."""
    c = celda.strip().lstrip("-+")
    return bool(c) and c[0].isdigit()


# ── el gráfico ──────────────────────────────────────────────────────────────────────

def test_la_trayectoria_se_dibuja_aunque_haya_UNA_sola_proyeccion_vigente():
    """Es el caso REAL de producción: una vigente y seis escenarios, y no se dibujaba nada."""
    from modules.macro_monitor import products_forecast as pf

    una_sola = [dict(pf._SAMPLE_PAYLOAD["proyecciones"][0])]
    args = _render_args(proyecciones=una_sola)
    charts = args.get("charts") or []
    assert charts, "con una vigente y seis escenarios no se dibujó ningún gráfico"
    items = charts[0]["items"]
    assert len(items) >= 3, (
        f"el gráfico trae {len(items)} punto(s): los escenarios de §3 no entraron")


def test_el_grafico_DISTINGUE_un_escenario_de_un_pronostico():
    """§3 existe para sostener esa distinción; fundirlos en una línea la borra.

    Un escenario no tiene track record y no ancla ninguna afirmación. Dibujarlo como si fuera
    un pronóstico es exactamente lo que la sección se toma tres párrafos en desmentir.
    """
    from modules.macro_monitor import products_forecast as pf

    args = _render_args()
    charts = args.get("charts") or []
    assert charts, "no hay gráfico que juzgar"
    etiquetas = [str(lbl) for lbl, _v in charts[0]["items"]]
    horizontes_esc = {e["horizonte"] for e in pf._SAMPLE_PAYLOAD["escenarios"]}
    de_escenario = [e for e in etiquetas if any(h in e for h in horizontes_esc)]
    assert de_escenario, "los escenarios no llegaron al gráfico"
    for e in de_escenario:
        assert e not in horizontes_esc, (
            f"«{e}» va en el gráfico igual que un pronóstico vigente, sin marca de escenario")


# ── los títulos y las secciones que faltaban ────────────────────────────────────────

def test_no_hay_DOS_secciones_llamadas_metodologia():
    """§6 «Metodología y límites» y §8 «Metodología y fuentes» en el mismo índice."""
    import app.main  # noqa: F401
    from modules.macro_monitor.products_forecast import _SECTION_TITLES
    from shared.products.report_sections import METHODOLOGY_KEY

    propios = [t for t in _SECTION_TITLES.values() if t.lower().startswith("metodolog")]
    assert not propios, (
        f"el producto titula {propios} y el framework agrega su «Metodología y fuentes» "
        f"({METHODOLOGY_KEY}): dos secciones que empiezan igual en el mismo índice")


@pytest.mark.parametrize("clave", ["resumen_ejecutivo", "proposito_y_alcance"])
def test_el_informe_abre_con_lo_que_un_lector_usa_para_decidir_si_sigue(clave):
    """El estándar que el eje de valuación recibió y éste no."""
    import app.main  # noqa: F401
    from modules.macro_monitor.products_forecast import _SECTION_TITLES
    from shared.products.registry import get_product

    assert clave in _SECTION_TITLES, f"falta la sección «{clave}»"
    prod = get_product(SECTOR)
    for tier in (ProductTier.insight, ProductTier.deep_dive):
        secciones = prod.product_manifest().require_level(tier).sections
        assert clave in secciones, f"«{clave}» no se sirve en {tier.value}"


def test_el_resumen_ejecutivo_se_COMPUTA_del_mismo_payload():
    """Nunca escrito a mano ni traído de la muestra: sería la vidriera mintiendo otra vez."""
    from modules.macro_monitor import products_forecast as pf

    p = dict(pf._SAMPLE_PAYLOAD)
    p["proyecciones"] = [dict(p["proyecciones"][0], punto=9.99, horizonte="2099-Q4")]
    texto = pf._md_resumen_ejecutivo(p)
    assert "9.99" in texto or "9,99" in texto, (
        f"el resumen no refleja el payload que recibe:\n{texto}")
