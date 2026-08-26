"""El informe ABIERTO de una ley: el tercer entregable, y el único que se comparte.

Los dos primeros —informe técnico y dictamen— son confidenciales del cliente que los
encarga. Éste no tiene destinatario, y eso cambia dos cosas que los tests vigilan: el
REGISTRO (prosa externa, sin andamiaje de método) y lo que NO puede decir (el veredicto de
cumplimiento, que es lo que el cliente pagó).
"""
import pytest

from modules.law_intel.informe_abierto import (ADVERTENCIA_DEL_REGISTRO, DEUDOR_EN_PROSA,
                                               ESTADO_EN_PROSA, MARCA, SECCIONES_EN_ORDEN,
                                               TITULOS, _recortar, construir)
from modules.law_intel.registro import expedientes

EXPEDIENTES = expedientes()


@pytest.mark.parametrize("eid", EXPEDIENTES)
class TestSirveACUALQUIERley:
    def test_construye_sin_romperse(self, eid):
        """Una ley de obligaciones sin indicadores y una de 90 indicadores tienen que salir
        las dos: es el mismo seam que probó el expediente de la 167-21."""
        d = construir(eid)
        assert d["titulo"] and d["tablas"]

    def test_siempre_trae_la_tabla_de_ALCANCE(self, eid):
        assert construir(eid)["tablas"][0][0] == "Alcance de la medición"

    def test_todas_las_secciones_declaradas_tienen_TEXTO(self, eid):
        sec = construir(eid)["secciones"]
        for k in SECCIONES_EN_ORDEN:
            assert sec.get(k, "").strip(), f"la sección «{k}» sale vacía"

    def test_toda_seccion_tiene_TITULO(self, eid):
        assert set(SECCIONES_EN_ORDEN) <= set(TITULOS)


@pytest.mark.parametrize("eid", EXPEDIENTES)
class TestElREGISTROesEXTERNO:
    """El lector está fuera de SDQ: ve la conclusión en prosa, no el método por su nombre."""

    def test_no_aparece_andamiaje_de_METODO(self, eid):
        d = construir(eid)
        texto = " ".join(d["secciones"].values())
        for molde in ("BLUF", "Bottom Line", "Hallazgo crítico", "Hallazgo de alto",
                      "Severidad:", "Lectura SDQ"):
            assert molde not in texto, f"«{molde}» es andamiaje interno y no sale del edificio"

    def test_el_vocabulario_INTERNO_se_traduce(self, eid):
        """`sin_registro_publico` y `universo` son jerga nuestra; el lector no tiene por qué
        conocer nuestro esquema."""
        filas = [f for t in construir(eid)["tablas"] for f in t[1]]
        crudo = {"sin_registro_publico", "cumplida_tarde", "pendiente_no_vencida",
                 "universo", "indeterminado", "organo"}
        for fila in filas:
            assert not (set(str(c) for c in fila) & crudo), f"jerga sin traducir en {fila}"

    def test_TODO_estado_del_expediente_tiene_traduccion(self, eid):
        from modules.law_intel.obligaciones import ESTADOS, cargar_obligaciones
        for o in cargar_obligaciones(eid):
            assert o.estado in ESTADO_EN_PROSA, f"estado «{o.estado}» sin prosa declarada"
            assert o.deudor["tipo"] in DEUDOR_EN_PROSA
        assert set(ESTADOS) <= set(ESTADO_EN_PROSA), (
            "un estado nuevo del vocabulario saldría crudo en un documento que se comparte")


@pytest.mark.parametrize("eid", EXPEDIENTES)
class TestLoQueNOpuedeDecir:
    def test_no_publica_el_VEREDICTO_de_cumplimiento(self, eid):
        """Ese análisis se prepara por encargo. Publicarlo el mismo día en un documento
        abierto le quita al cliente lo que pagó."""
        texto = " ".join(construir(eid)["secciones"].values()).lower()
        for palabra in ("alcanzó su meta", "no alcanzará", "incumple la meta",
                        "tasa de cumplimiento"):
            assert palabra not in texto

    def test_la_advertencia_del_registro_ACOMPAÑA_a_las_obligaciones(self, eid):
        """«No se encontró registro» y «no se hizo» son afirmaciones distintas."""
        d = construir(eid)
        if any(t[0] == "Qué ordena la norma" for t in d["tablas"]):
            assert ADVERTENCIA_DEL_REGISTRO in d["secciones"]["lo_que_ordena"]

    def test_la_marca_dice_que_se_COMPARTE(self, eid):
        assert "abierto" in MARCA.lower()


class TestElRECORTEnoParteLasPalabras:
    def test_corta_en_el_ultimo_espacio(self):
        """«dentro de quinc» y «vigencia d» se imprimen tal cual en la tabla."""
        assert _recortar("Evaluar el análisis dentro de quince días hábiles", 26) == \
            "Evaluar el análisis…"

    def test_no_toca_lo_que_ya_entra(self):
        assert _recortar("corto", 40) == "corto"

    def test_colapsa_los_espacios_del_expediente(self):
        assert _recortar("dos   espacios", 40) == "dos espacios"


def test_el_nombre_del_archivo_DISTINGUE_la_norma():
    """Dos leyes producían el mismo archivo y la segunda descarga pisaba a la primera."""
    from shared.products.filenames import report_filename
    nombres = {report_filename(naturaleza="Informe-Abierto", sector_key="law",
                               sujeto=n, periodo="2026-08-25", fmt="pdf")
               for n in ("Ley 167-21", "Ley 1-12", "Decreto 337-24")}
    assert len(nombres) == 3


def test_la_ruta_esta_registrada():
    import modules.law_intel.api.router as r
    assert any("informe-abierto" in x.path for x in r.router.routes)
