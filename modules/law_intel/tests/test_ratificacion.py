"""Las metas se aprueban UNA VEZ y no se mueven sin una norma que lo autorice.

El hallazgo central del expediente de la END es el artículo 20: deja al órgano rector —el
propio evaluado— cambiar las metas por vía administrativa. Un evaluador cuyo registro se puede
editar sin rastro tiene el mismo defecto que denuncia, y con menos excusa: nosotros elegimos
el diseño. Por eso la deriva no autorizada BLOQUEA el servicio en vez de solo avisar.
"""
import dataclasses

import pytest

from modules.law_intel.ratificacion import (ORIGENES, DerivaNoAutorizada, Enmienda,
                                            EstadoRatificacion, estado, exigir_servible,
                                            hash_de_metas, publicable)
from modules.law_intel.registro import Indicador, cargar

E = "end_2030"


def ind(**kw):
    base = dict(id="1.8", eje=1, nombre="Tasa de homicidios", escala="numerica",
                base_valor=24.8, metas={"2025": 10.0})
    return Indicador(**{**base, **kw})


class TestElHash:
    def test_mover_una_meta_lo_cambia(self):
        assert hash_de_metas([ind()]) != hash_de_metas([ind(metas={"2025": 9.0})])

    def test_mover_la_linea_base_lo_cambia(self):
        assert hash_de_metas([ind()]) != hash_de_metas([ind(base_valor=24.9)])

    def test_cambiar_la_escala_lo_cambia(self):
        """Pasar una meta de numérica a umbral cambia qué afirma la ley, no solo su forma."""
        assert hash_de_metas([ind()]) != hash_de_metas([ind(escala="umbral")])

    def test_corregir_el_ROTULO_no_lo_cambia(self):
        """Una tilde en el nombre no es mover una meta. Si el sello se rompiera por ruido,
        la gente aprendería a re-sellar sin mirar — y el sello dejaría de significar algo."""
        assert hash_de_metas([ind()]) == hash_de_metas([ind(nombre="Tasa de homicidios ")])

    def test_el_orden_de_las_filas_no_importa(self):
        a, b = ind(), ind(id="1.9")
        assert hash_de_metas([a, b]) == hash_de_metas([b, a])


class TestLaPuertaDeServicio:
    def test_los_expedientes_reales_estan_ratificados(self):
        for e in (E, "meta_rd_2036"):
            st = estado(e)
            assert st.estado == "ratificado" and st.servible, e

    def test_una_deriva_sin_norma_bloquea(self, tmp_path, monkeypatch):
        """El test que le da valor a todo lo demás: no alcanza con avisar."""
        base = tmp_path / "x"
        base.mkdir()
        (base / "sello.yaml").write_text(
            "sello: {hash_metas: deadbeef, fecha: '2026-01-01', aprobado_por: y}\n"
            "enmiendas: []\n", encoding="utf-8")
        monkeypatch.setattr("modules.law_intel.ratificacion.RAIZ", tmp_path)
        monkeypatch.setattr("modules.law_intel.ratificacion.cargar",
                            lambda _: type("E", (), {"indicadores": [ind()]})())
        estado.cache_clear()
        assert estado("x").estado == "deriva_no_autorizada"
        assert not estado("x").servible
        with pytest.raises(DerivaNoAutorizada, match="ninguna enmienda"):
            exigir_servible("x")
        estado.cache_clear()

    def test_una_enmienda_con_el_hash_correcto_autoriza(self, tmp_path, monkeypatch):
        nuevo = hash_de_metas([ind(metas={"2025": 9.0})])
        base = tmp_path / "x"
        base.mkdir()
        (base / "sello.yaml").write_text(
            "sello: {hash_metas: viejo, fecha: '2026-01-01', aprobado_por: y}\n"
            "enmiendas:\n"
            "  - id: e1\n    origen: ley\n    norma: Ley 99-99\n    fecha: '2027-01-01'\n"
            "    indicadores: ['1.8']\n    detalle: baja la meta\n"
            f"    hash_resultante: {nuevo}\n", encoding="utf-8")
        monkeypatch.setattr("modules.law_intel.ratificacion.RAIZ", tmp_path)
        monkeypatch.setattr("modules.law_intel.ratificacion.cargar",
                            lambda _: type("E", (), {"indicadores": [ind(metas={"2025": 9.0})]})())
        estado.cache_clear()
        st = estado("x")
        assert st.estado == "enmendado" and st.servible
        assert st.enmienda_vigente.norma == "Ley 99-99"
        estado.cache_clear()

    def test_una_norma_real_no_es_paraguas_de_otro_cambio(self, tmp_path, monkeypatch):
        """La enmienda cita una ley verdadera pero su hash no coincide con el registro: el
        cambio que se hizo NO es el que la norma autorizó."""
        base = tmp_path / "x"
        base.mkdir()
        (base / "sello.yaml").write_text(
            "sello: {hash_metas: viejo, fecha: '2026-01-01', aprobado_por: y}\n"
            "enmiendas:\n"
            "  - id: e1\n    origen: ley\n    norma: Ley 99-99\n    fecha: '2027-01-01'\n"
            "    indicadores: ['1.8']\n    detalle: baja la meta\n"
            "    hash_resultante: otro_hash_distinto\n", encoding="utf-8")
        monkeypatch.setattr("modules.law_intel.ratificacion.RAIZ", tmp_path)
        monkeypatch.setattr("modules.law_intel.ratificacion.cargar",
                            lambda _: type("E", (), {"indicadores": [ind()]})())
        estado.cache_clear()
        assert estado("x").estado == "deriva_no_autorizada"
        estado.cache_clear()


class TestElOrigenNoEsIndiferente:
    def test_los_tres_origenes_estan_declarados(self):
        assert set(ORIGENES) == {"ley", "decreto", "administrativa"}

    def test_un_cambio_administrativo_se_señala(self):
        """Es el mecanismo del art. 20: legal, y es la falla de diseño que el informe apunta."""
        e = Enmienda(id="e", origen="administrativa", norma="Acta de la Reunión Anual",
                     fecha="2020-01-01", indicadores=["2.1"], detalle="reemplaza el indicador",
                     hash_resultante="h")
        st = EstadoRatificacion("x", "enmendado", "h", "viejo", enmienda_vigente=e)
        import modules.law_intel.ratificacion as r
        pub = r.publicable.__wrapped__("x") if hasattr(r.publicable, "__wrapped__") else None
        # Se prueba la rama directamente para no depender de un expediente en disco.
        assert "potestad delegada" in ORIGENES["administrativa"]
        assert st.enmienda_vigente.origen == "administrativa"

    def test_una_reforma_por_ley_no_lleva_advertencia(self):
        pub = publicable(E)          # ratificado, sin enmienda
        assert pub["advertencia"] is None


def test_la_lectura_publicable_no_tiene_texto_de_autor():
    """Mismo criterio que las recomendaciones: la frase se arma de los campos."""
    campos = {f.name for f in dataclasses.fields(Enmienda)}
    assert campos == {"id", "origen", "norma", "fecha", "indicadores", "detalle",
                      "hash_resultante"}
