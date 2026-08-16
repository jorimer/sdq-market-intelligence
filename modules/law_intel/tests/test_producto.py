"""El producto engancha al pipeline sin romper ninguna de sus reglas.

El test que más importa es el de la HUELLA. En los demás sectores el dato vive en la base, así
que un arreglo mueve el payload y la caché —que no tiene TTL— regenera. Acá el dato de la ley
vive en archivos del repositorio: sin la huella, corregir una meta del CSV dejaría a los
informes ya generados sirviendo el texto viejo indefinidamente. Ya pasó en esta plataforma con
un arreglo de contexto que se desplegó y no invalidó nada.
"""
import pytest

from modules.law_intel.ai_context import law_ai_context, secciones_sin_dato
from modules.law_intel.products import (AI_CONTEXT_FILES, SECTOR_KEY, LawProduct,
                                        expediente_fingerprint, law_manifest)
from shared.products import ProductTier
from shared.products.registry import CATALOG_BY_KEY, get_product, is_implemented

E = "end_2030"


class TestLaHuellaDelExpediente:
    def test_cambiar_el_registro_cambia_la_huella(self, tmp_path, monkeypatch):
        """Sin esto, arreglar una cifra del CSV no invalida ningún informe ya generado."""
        base = tmp_path / "falso"
        base.mkdir()
        (base / "indicadores.csv").write_text("id,eje\n1.1,1\n", encoding="utf-8")
        monkeypatch.setattr("modules.law_intel.products.RAIZ", tmp_path)
        antes = expediente_fingerprint("falso")
        (base / "indicadores.csv").write_text("id,eje\n1.1,2\n", encoding="utf-8")
        assert expediente_fingerprint("falso") != antes

    def test_agregar_un_archivo_tambien_la_cambia(self, tmp_path, monkeypatch):
        """Un `obligaciones.yaml` nuevo cambia lo que el informe afirma."""
        base = tmp_path / "falso"
        base.mkdir()
        (base / "a.csv").write_text("x", encoding="utf-8")
        monkeypatch.setattr("modules.law_intel.products.RAIZ", tmp_path)
        antes = expediente_fingerprint("falso")
        (base / "obligaciones.yaml").write_text("y", encoding="utf-8")
        assert expediente_fingerprint("falso") != antes

    def test_la_huella_viaja_en_el_payload(self):
        """Fuera del payload, la caché no la ve: es el único lugar donde sirve."""
        s = LawProduct().snapshot(ProductTier.deep_dive, "2025", E)
        assert s.payload["expediente_fingerprint"] == expediente_fingerprint(E)

    def test_expedientes_distintos_tienen_huellas_distintas(self):
        assert expediente_fingerprint(E) != expediente_fingerprint("meta_rd_2036")


class TestContratoDeProducto:
    def test_esta_en_el_catalogo_y_registrado(self):
        assert SECTOR_KEY in CATALOG_BY_KEY
        assert is_implemented(SECTOR_KEY)
        assert get_product(SECTOR_KEY) is not None

    def test_el_selector_lista_los_instrumentos(self):
        vals = {o["value"] for o in LawProduct().scope_options()}
        assert {"end_2030", "meta_rd_2036"} <= vals

    def test_un_expediente_inexistente_es_error_en_español(self):
        with pytest.raises(ValueError, match="No existe el expediente"):
            LawProduct().snapshot(ProductTier.insight, "2025", "ley-inventada")

    def test_el_pulse_no_nombra_la_entidad(self):
        """Granularidad `system`: el sensor de anonimización del ensamblador lo verifica."""
        assert LawProduct().snapshot(ProductTier.pulse, "2025", E).entity_name is None
        assert LawProduct().snapshot(ProductTier.insight, "2025", E).entity_name

    def test_los_tres_niveles_declaran_secciones(self):
        for tier in (ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive):
            assert law_manifest().require_level(tier).sections


class TestHonestidadDelProducto:
    def test_sin_bindings_verificados_no_se_declara_aprobado(self):
        """Declararse validado con cobertura cero sería exactamente lo que el módulo denuncia."""
        v = LawProduct().validation_state()
        assert v.approved is False and v.score == 0.0
        assert "verificacion" in v.notes

    def test_la_seccion_de_cumplimiento_se_declara_vacia(self):
        """Un Deep Dive relleno es peor que uno más corto."""
        ctx = law_ai_context(E, "2025")
        assert "cumplimiento" in secciones_sin_dato(ctx)

    def test_la_cobertura_reportada_es_la_real(self):
        assert LawProduct().data_signals().coverage == 0.0


class TestContextoDeIA:
    def test_las_relaciones_llegan_resueltas(self):
        """El modelo copia veredictos; no deriva ninguno de una meta y un dato."""
        ctx = law_ai_context(E, "2025")
        assert ctx["veredictos_por_indicador_computados"]["por_veredicto"]
        assert all("lectura_ya_redactada" in c
                   for c in ctx["contradicciones_proceso_vs_resultado_computadas"])
        assert all("texto" in r for r in ctx["recomendaciones_ya_redactadas"])

    def test_prohibe_el_eufemismo_del_informe_oficial(self):
        v = law_ai_context(E, "2025")["vocabulario_obligatorio"]
        assert "avance moderado" in v["no_alcanzara"]

    def test_prohibe_afirmar_incumplimiento_sin_verificar(self):
        assert "sin_registro_publico" in law_ai_context(E, "2025")["regla_de_afirmacion"]

    def test_los_dos_denominadores_van_explicitos(self):
        d = law_ai_context(E, "2025")["denominadores_del_registro"]
        assert d["indicadores_numerados_de_la_ley"] == 90
        assert d["filas_medibles_con_subfilas"] == 135

    def test_el_cierre_del_informe_llega_al_modelo(self):
        """Si la brecha y la recomendación no están en el contexto, la sección sale de memoria."""
        ctx = law_ai_context(E, "2025")
        assert ctx["brechas_de_medicion"]["con_brecha"] > 0
        assert ctx["recomendaciones_ya_redactadas"]
        assert "nunca la política" in ctx["alcance_de_la_recomendacion"]


def test_declara_sus_fuentes_de_contexto():
    """`AI_CONTEXT_FILES` es lo que mete estos archivos en la regla del sujeto y en la huella
    de la caché de narrativas. Sin declararlo, la mitad del contexto queda fuera de las dos."""
    assert "ai_context.py" in AI_CONTEXT_FILES
    assert any("accionabilidad" in f for f in AI_CONTEXT_FILES)
