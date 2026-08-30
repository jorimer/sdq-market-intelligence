"""El mapa sectorial está registrado en TODAS sus superficies, y su muestra cierra sola.

Por qué existe este archivo. Un tipo de sección nuevo se registra de a uno en cinco lugares
—manifiesto, plantilla del modelo, ruta cerebro, título del PDF, etiqueta del frontend— y
**ninguno falla**: cada omisión lo hace desaparecer en un sitio distinto y en silencio. Al
anuario le faltaron cuatro registros y el defecto se descubrió en producción. Acá se exigen
los cinco juntos.

Y la muestra curada tiene una obligación extra: es la vidriera del producto, así que sus
cifras se leen con calculadora. Un mapa cuyas moras por sector no reconstruyen la morosidad
agregada de la propia muestra es lo primero que un comprador encuentra.
"""

import json
import pathlib

import pytest

from modules.banking_score import products as P
from modules.banking_score.products import SAMPLE_MAPA_SECTORIAL as MAPA
from modules.banking_score.reports import narrative as N
from modules.banking_score.reports import pdf_generator as PDF
from shared.narrative import claude_engine as CE

SECCION = "mapa_sectorial"
PLANTILLA = "banking_sector_map"


class TestRegistradoEnLasCincoSuperficies:
    def test_esta_en_el_manifiesto_del_deep_dive(self):
        assert SECCION in P._DEEP_DIVE_SECTIONS
        # Y NO en el Insight: exige el libro completo del sistema, que es lo que separa un
        # nivel del otro. Colarlo en Insight regalaría la lectura que sostiene el Deep Dive.
        assert SECCION not in P._INSIGHT_SECTIONS

    def test_la_seccion_resuelve_a_una_plantilla_que_EXISTE(self):
        """Sin esto el motor pide una plantilla inexistente y cae al relleno estático EN
        SILENCIO: el informe sale con un párrafo genérico y los tests siguen verdes."""
        assert N._SECTION_TO_TEMPLATE[SECCION] == PLANTILLA
        assert PLANTILLA in CE.THIN_TEMPLATES

    def test_va_por_la_ruta_CEREBRO_y_no_por_la_legacy(self):
        """La trampa del anuario: registrado en `THIN_TEMPLATES` pero ausente de
        `_CEREBRO_TEMPLATES`, el motor lo mandaba por la ruta legacy —donde la plantilla no
        existe— y servía el relleno. Salió a producción así."""
        assert PLANTILLA in N._CEREBRO_TEMPLATES

    def test_tiene_titulo_propio_en_el_PDF(self):
        """Sin línea propia, el fallback imprime el nombre de la variable capitalizado."""
        assert PDF.NARRATIVE_SECTION_TITLES[SECCION] == "Mapa Sectorial del Crédito"

    def test_tiene_etiqueta_en_el_FRONTEND(self):
        tsx = (pathlib.Path(__file__).parents[3]
               / "frontend/src/modules/platform/pages/ResearchPage.tsx").read_text()
        assert f"{SECCION}:" in tsx, (
            "la interfaz caería al fallback y mostraría «Mapa Sectorial» derivado de la "
            "clave, no la etiqueta del producto")

    def test_su_archivo_de_computo_esta_en_la_HUELLA_de_la_cache(self):
        """`ProductReportCache` no tiene TTL. Si el archivo que computa las brechas no está
        declarado, cambiar cómo se computa una brecha NO invalida nada y los informes ya
        generados sirven el texto viejo indefinidamente."""
        from modules.banking_score.ai_context_files import AI_CONTEXT_FILES
        assert "reports/mapa_sectorial.py" in AI_CONTEXT_FILES

    def test_tiene_relleno_estatico_SIN_cifras(self):
        """El relleno se sirve cuando no hay motor IA. Con cifras dentro, el guard numérico
        lo vetaría sin que nadie entienda por qué."""
        relleno = CE.STATIC_FALLBACKS[PLANTILLA] if hasattr(CE, "STATIC_FALLBACKS") else None
        if relleno is None:      # el dict cambió de nombre: lo buscamos por contenido
            fuente = pathlib.Path(CE.__file__).read_text()
            i = fuente.rindex(f'"{PLANTILLA}": (')
            relleno = fuente[i:i + 700]
        assert not [c for c in relleno if c.isdigit()], (
            "el relleno estático no debe traer cifras")


class TestLaMuestraCierraSola:
    def test_las_moras_por_sector_reconstruyen_la_morosidad_de_la_muestra(self):
        """1.9% es la morosidad que la muestra declara en `SAMPLE_SCORING`. Si las partes
        no dan el total, la primera persona que multiplique lo nota."""
        num = sum(s["deuda"] * s["mora_pct"] for s in MAPA["sectores"])
        den = sum(s["deuda"] for s in MAPA["sectores"])
        assert num / den == pytest.approx(
            P.SAMPLE_SCORING["indicators"]["morosidad"]["raw"], abs=0.01)

    def test_los_pesos_suman_cien(self):
        assert sum(s["peso_en_su_cartera_pct"]
                   for s in MAPA["sectores"]) == pytest.approx(100.0, abs=0.1)

    def test_la_deuda_por_sector_suma_el_credito_clasificado(self):
        assert sum(s["deuda"] for s in MAPA["sectores"]) == pytest.approx(
            MAPA["credito_clasificado"], rel=1e-6)

    @pytest.mark.parametrize("mio,suyo,brecha", [
        ("mora_pct", "mora_del_resto_del_sector_pct", "brecha_de_mora_pp"),
        ("tasa_promedio_ponderada_pct", "tasa_del_resto_del_sector_pct", "spread_de_tasa_pp"),
    ])
    def test_las_relaciones_de_la_muestra_estan_COMPUTADAS_y_no_escritas_a_ojo(
            self, mio, suyo, brecha):
        """La muestra es lo único del producto que se escribe a mano, así que es lo único
        donde una brecha puede quedar en desacuerdo con sus dos términos."""
        for s in MAPA["sectores"]:
            assert s[brecha] == pytest.approx(round(s[mio] - s[suyo], 2), abs=0.005), (
                f"{s['sector']}: {brecha} no coincide con {mio} − {suyo}")

    def test_la_atribucion_de_la_muestra_coincide_con_la_regla_del_modulo(self):
        """Escrita a mano, la etiqueta puede contradecir la brecha que tiene al lado."""
        from modules.banking_score.reports.mapa_sectorial import _atribuir
        for s in MAPA["sectores"]:
            assert s["atribucion"] == _atribuir(s["brecha_de_mora_pp"], s["material"])

    def test_la_narrativa_curada_solo_cita_cifras_que_estan_en_la_muestra(self):
        """El guard numérico veta una cifra sin respaldo. La narrativa curada NO pasa por el
        motor, así que nadie la juzga: si cita un número que la tabla no trae, sale
        publicado. Es la única prosa del producto sin veto."""
        import re
        texto = P.SAMPLE_NARRATIVES[SECCION]
        respaldo = set()
        for s in MAPA["sectores"]:
            for k, v in s.items():
                if isinstance(v, (int, float)):
                    respaldo.add(f"{abs(v):.2f}")
                    respaldo.add(f"{abs(v):g}")
        respaldo |= {f"{v:g}" for v in (1.9, 100)}   # la morosidad agregada y el porcentaje
        # «de 31 a 90 días» NOMBRA el tramo de mora de la SIB; no es una cifra medida sobre
        # esta entidad. Se retira del texto antes de buscar, en vez de admitir 31 y 90 como
        # respaldadas: admitirlas dejaría pasar cualquier otro uso de esos dos números.
        texto = texto.replace("de 31 a 90 días", "de treinta y uno a noventa días")
        citadas = re.findall(r"\d+(?:\.\d+)?", texto)
        huerfanas = [c for c in citadas if c not in respaldo]
        assert not huerfanas, f"cifras sin respaldo en la muestra: {huerfanas}"


def test_el_barrido_encontro_algo():
    """Toda aserción de ausencia lleva al lado la prueba de que había dónde mirar."""
    assert MAPA["sectores"], "la muestra no tiene sectores"
    assert json.dumps(MAPA)   # serializable: viaja en el payload del snapshot
