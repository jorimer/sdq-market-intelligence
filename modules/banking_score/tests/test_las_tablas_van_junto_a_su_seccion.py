"""Cada tabla se imprime junto al párrafo que la interpreta, y NINGUNA se pierde.

El cambio. Las tablas del informe se imprimían todas en un bloque de datos separado de la
narrativa por un salto de página. Para las que encuadran el documento entero —cuadro de
mando, indicadores, trayectoria— está bien: abren el informe. Pero cuatro de ellas son el
respaldo de un párrafo concreto —la de pares sostiene el comparativo, la macro el entorno
operativo, la de sensibilidad la recomendación, la del mapa su propia sección— y veinte
páginas antes del texto que las lee obligan a sostenerlas de memoria.

El riesgo del cambio, y por qué este archivo existe. Reordenar puede hacer DESAPARECER una
tabla: si su sección dueña no se está narrando —un `scorecard` no lleva comparativo— y la
tabla ya no está en el bloque de datos, no está en ninguna parte. Nada fallaría; el PDF
saldría y le faltaría una tabla. Es la forma exacta en que este repo pierde cosas.
"""

import asyncio
import pathlib

import pdfplumber

from modules.banking_score.reports.pdf_generator import generate_pdf_report

PERIODO = "2026-03-31"

_MAPA = {
    "entidad": "Banco Prueba", "corte": PERIODO, "credito_clasificado": 300_000_000.0,
    "sectores": [{
        "sector": "F - CONSTRUCCIÓN", "deuda": 300_000_000.0,
        "peso_en_su_cartera_pct": 100.0, "cuota_del_sector_pct": 30.0,
        "mora_pct": 6.51, "mora_del_resto_del_sector_pct": 1.13,
        "brecha_de_mora_pp": 5.38,
        "tasa_promedio_ponderada_pct": 13.31, "tasa_del_resto_del_sector_pct": 11.82,
        "spread_de_tasa_pp": 1.49,
        "atribucion": "idiosincratico_peor", "material": True,
    }],
}
_PEERS = {"metric_label": "Activos", "cr5": 71.2, "cr10": 87.4, "hhi": 1380}
_SCORING = {
    "overall_score": 70.0, "banda_ejecucion": "Competitiva", "banda_resiliencia": "Sólida",
    "sub_components": {"solidez": 70, "calidad": 60, "eficiencia": 65,
                       "liquidez": 72, "diversificacion": 55},
    "indicators": {"morosidad": {"raw": 6.5, "score": 40, "available": True}},
    "mapa_sectorial": _MAPA,
}
_SECCIONES = ["executive_summary", "diversificacion", "mapa_sectorial", "comparative"]
_NARRATIVAS = {s: f"Análisis de {s}." for s in _SECCIONES}


def _texto(tmp_path, **kw) -> str:
    ruta = asyncio.run(generate_pdf_report(
        report_type="full_rating", bank_name="Banco Prueba",
        scoring_result=kw.pop("scoring_result", _SCORING), period=PERIODO,
        output_dir=str(tmp_path), **kw))
    assert pathlib.Path(ruta).exists()
    # `pdfplumber` y no `pypdf`: es la que el repo declara en requirements. Un test que
    # importa una dependencia no declarada pasa en la máquina de quien la instaló a mano y
    # muere en CI.
    with pdfplumber.open(ruta) as pdf:
        return "\n".join((pg.extract_text() or "") for pg in pdf.pages)


def _pos(texto: str, aguja: str) -> int:
    i = texto.find(aguja)
    assert i >= 0, f"no se encontró «{aguja}» en el PDF"
    return i


class TestLaTablaVaJuntoASuParrafo:
    def test_el_mapa_se_imprime_DENTRO_de_su_seccion(self, tmp_path):
        t = _texto(tmp_path, narratives=_NARRATIVAS, sections=_SECCIONES)
        titulo = _pos(t, "Mapa Sectorial del Crédito")
        tabla = _pos(t, "Posición por sector frente al resto del sistema")
        siguiente = _pos(t, "Análisis Comparativo")
        assert titulo < tabla < siguiente, (
            "la tabla debe caer entre el título de su sección y la sección siguiente")

    def test_el_bloque_de_pares_cae_en_el_COMPARATIVO(self, tmp_path):
        t = _texto(tmp_path, narratives=_NARRATIVAS, sections=_SECCIONES,
                   peer_block=_PEERS)
        assert _pos(t, "Análisis Comparativo") < _pos(t, "1380")

    def test_las_tablas_de_ENCUADRE_siguen_abriendo_el_informe(self, tmp_path):
        """El cuadro de mando y los indicadores no pertenecen a una sección: son el mapa
        del documento entero y su lugar es el principio."""
        t = _texto(tmp_path, narratives=_NARRATIVAS, sections=_SECCIONES)
        assert _pos(t, "Resumen Ejecutivo") > _pos(t, "Diversificación")


class TestNingunaTablaDesaparece:
    def test_si_su_seccion_NO_se_narra_la_tabla_vuelve_al_bloque_de_datos(self, tmp_path):
        """El defecto que introduciría este cambio si nadie lo vigilara: un `scorecard` no
        lleva comparativo, así que la tabla de pares no tendría dónde caer."""
        t = _texto(tmp_path,
                   narratives={"executive_summary": "Análisis."},
                   sections=["executive_summary"],
                   peer_block=_PEERS)
        assert "1380" in t, ("la tabla de pares desapareció: su sección no se narra y "
                             "tampoco volvió al bloque de datos")

    def test_el_mapa_tampoco_desaparece_sin_su_seccion(self, tmp_path):
        t = _texto(tmp_path,
                   narratives={"executive_summary": "Análisis."},
                   sections=["executive_summary"])
        assert "Posición por sector frente al resto del sistema" in t

    def test_sin_narrativa_alguna_las_tablas_se_imprimen_igual(self, tmp_path):
        """El PDF sin motor IA sigue siendo un entregable de datos."""
        t = _texto(tmp_path, peer_block=_PEERS)
        assert "1380" in t
        assert "Posición por sector frente al resto del sistema" in t


def test_el_barrido_encontro_un_pdf_con_contenido(tmp_path):
    """Una aserción de presencia sobre un PDF vacío pasaría sola si el extractor fallara."""
    t = _texto(tmp_path, narratives=_NARRATIVAS, sections=_SECCIONES, peer_block=_PEERS)
    assert len(t) > 1500, "el extractor no devolvió texto: las aserciones no probarían nada"


class TestLaTablaGeografica:
    """La provincia estaba en la base y no salía por ninguna superficie."""

    _MAPA_CON_PROVINCIAS = {
        **_MAPA,
        "provincias": [
            {"provincia": "DISTRITO NACIONAL", "deuda": 200_000_000.0,
             "peso_en_su_cartera_pct": 66.67, "peso_de_la_provincia_en_el_pais_pct": 40.0,
             "sobre_representacion_pp": 26.67, "mora_pct": 8.0,
             "mora_del_resto_del_pais_en_la_provincia_pct": 2.0, "brecha_de_mora_pp": 6.0,
             "sectores_en_que_presta": 12},
            {"provincia": "SIN PROVINCIA", "deuda": 100_000_000.0,
             "peso_en_su_cartera_pct": 33.33, "peso_de_la_provincia_en_el_pais_pct": 5.0,
             "sobre_representacion_pp": 28.33, "mora_pct": None,
             "mora_del_resto_del_pais_en_la_provincia_pct": None, "brecha_de_mora_pp": None,
             "sectores_en_que_presta": 3},
        ],
    }

    def test_se_imprime_DENTRO_de_la_misma_seccion_que_la_sectorial(self, tmp_path):
        scoring = {**_SCORING, "mapa_sectorial": self._MAPA_CON_PROVINCIAS}
        t = _texto(tmp_path, scoring_result=scoring, narratives=_NARRATIVAS,
                   sections=_SECCIONES)
        titulo = _pos(t, "Mapa Sectorial del Crédito")
        geo = _pos(t, "Dónde presta, contra dónde presta el país")
        siguiente = _pos(t, "Análisis Comparativo")
        assert titulo < geo < siguiente

    def test_va_DEBAJO_de_la_sectorial_porque_el_parrafo_las_lee_juntas(self, tmp_path):
        scoring = {**_SCORING, "mapa_sectorial": self._MAPA_CON_PROVINCIAS}
        t = _texto(tmp_path, scoring_result=scoring, narratives=_NARRATIVAS,
                   sections=_SECCIONES)
        assert _pos(t, "Posición por sector") < _pos(t, "Dónde presta, contra dónde")

    def test_SIN_PROVINCIA_aparece_y_el_pie_explica_qué_es(self, tmp_path):
        scoring = {**_SCORING, "mapa_sectorial": self._MAPA_CON_PROVINCIAS}
        t = _texto(tmp_path, scoring_result=scoring, narratives=_NARRATIVAS,
                   sections=_SECCIONES)
        assert "SIN PROVINCIA" in t
        assert "cuyo rótulo la fuente no trae" in t

    def test_sin_provincias_la_seccion_sale_igual_con_su_tabla_sectorial(self, tmp_path):
        """Los cortes anteriores al backfill no tienen provincia; la sección no se rompe."""
        t = _texto(tmp_path, narratives=_NARRATIVAS, sections=_SECCIONES)
        assert "Posición por sector" in t
        assert "Dónde presta, contra dónde" not in t
