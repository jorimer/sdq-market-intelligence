"""La atribución a la UIT es CONDICIÓN de la licencia, y viaja computada al narrador.

**El caso.** El 2026-08-18 la División de Datos y Analítica de las TIC de la UIT autorizó por
escrito el uso de los datos de ITU DataHub «como insumo para productos analíticos
comerciales, siempre que la UIT (ITU) sea citada adecuadamente como fuente». Nombrarla dejó
de ser buena práctica y pasó a ser la condición sobre la que se concedió el permiso.

**Lo que había.** El contexto de IA del eje declaraba su fuente en una constante —«INDOTEL
(boletín trimestral de indicadores)»— para TODOS los períodos, incluidos los anuales, que
produce la UIT desde que el boletín de INDOTEL se congeló en 2022-Q1 y sus trimestres se
retiraron de la base. O sea: no es que faltara la atribución a la UIT, es que el narrador
recibía la atribución de OTRO emisor. El endpoint tenía el mismo defecto y ya se había
arreglado —``test_source_label``— pero el contexto de IA no, que es el patrón que la doctrina
nombra: son superficies distintas y arreglar una sola deja el documento contradiciéndose.

**Qué fijan estos tests.** Que el emisor se compute del período, que el texto de la
atribución venga del registro de licencias y no de una copia en el módulo, y que la regla
llegue al modelo junto con el texto — una lista sin la regla se lee como información de
contexto, no como obligación.
"""
from modules.telecom_intel.ai_context import telecom_ai_context
from modules.telecom_intel.sources import INDOTEL, ITU, emisor_del_periodo
from shared.data.itu_client import ITUClient
from shared.data.licenses import atribucion_exigida

_INDEX = {"telecom_score": 61.0, "band": "B", "coverage": 1.0,
          "dimensions": {}, "metrics": {}}


class TestElEmisorSeComputaDelPeriodo:

    def test_un_periodo_anual_es_de_la_uit(self):
        assert emisor_del_periodo("2024") is ITU

    def test_un_periodo_trimestral_es_del_boletin_congelado(self):
        assert emisor_del_periodo("2022-Q1") is INDOTEL

    def test_sin_periodo_cae_en_la_fuente_VIGENTE(self):
        """Ante lo ilegible se nombra a quien produce hoy, no al emisor muerto."""
        assert emisor_del_periodo(None) is ITU and emisor_del_periodo("") is ITU

    def test_la_licencia_del_emisor_se_importa_del_conector(self):
        """Copiarla es como se pierde una corrección: el original cambia y la copia no."""
        assert ITU.license == ITUClient.license


class TestLaAtribucionLlegaAlNarrador:

    def test_el_contexto_de_un_periodo_de_la_uit_la_trae(self):
        ctx = telecom_ai_context(_INDEX, "2024")
        assert "UIT" in ctx["atribucion_obligatoria"]
        assert ctx["atribucion_obligatoria"] == atribucion_exigida(ITUClient.license)

    def test_el_texto_NO_esta_escrito_en_el_modulo(self):
        """Sale del registro de licencias, que es donde vive la obligación."""
        import pathlib
        fuente = pathlib.Path(__file__).resolve().parents[1]
        escrito = "\n".join(
            f.read_text(encoding="utf-8")
            for f in (fuente / "ai_context.py", fuente / "sources.py"))
        assert atribucion_exigida(ITUClient.license) not in escrito

    def test_la_regla_viaja_con_el_texto(self):
        """Sin la regla, el modelo lee la atribución como un dato más del contexto."""
        ctx = telecom_ai_context(_INDEX, "2024")
        assert "DEBE nombrar" in ctx["regla_de_la_atribucion"]
        assert "condición de la licencia" in ctx["regla_de_la_atribucion"]

    def test_un_emisor_que_no_la_exige_no_inventa_una(self):
        """Inflarla haría que el informe repita atribuciones que nadie pide."""
        ctx = telecom_ai_context(_INDEX, "2022-Q1")
        assert ctx["atribucion_obligatoria"] == ""
        assert "no hay texto obligatorio" in ctx["regla_de_la_atribucion"]


class TestRegresionDelEmisorEquivocado:
    """El defecto exacto: el contexto nombraba a INDOTEL para dato de la UIT."""

    def test_un_periodo_anual_NO_menciona_a_indotel(self):
        ctx = telecom_ai_context(_INDEX, "2024")
        assert "INDOTEL" not in ctx["source"], ctx["source"]
        assert "INDOTEL" not in ctx["note"], ctx["note"]

    def test_un_periodo_anual_nombra_a_la_uit(self):
        ctx = telecom_ai_context(_INDEX, "2024")
        assert "ITU DataHub" in ctx["source"]

    def test_un_periodo_trimestral_sigue_nombrando_a_indotel(self):
        """No se arregla borrando al emisor histórico: esos puntos SÍ son suyos."""
        ctx = telecom_ai_context(_INDEX, "2022-Q1")
        assert "INDOTEL" in ctx["source"]
