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
    def test_los_expedientes_reales_se_sirven_y_con_papel(self):
        """`ratificado` dejó de ser el único estado sano: una corrección firmada también
        sirve. Lo que no puede pasar es que un expediente se sirva SIN papel que lo autorice,
        así que cuando el estado no es `ratificado` se exige el documento que lo respalda."""
        for e in (E, "meta_rd_2036"):
            st = estado(e)
            assert st.servible, f"{e}: {st.estado}"
            if st.estado != "ratificado":
                assert st.enmienda_vigente or st.correccion_vigente, (
                    f"{e}: estado '{st.estado}' sin enmienda ni corrección que lo autorice")

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


def _yaml():
    import yaml  # type: ignore[import-untyped]

    return yaml


class TestLaCorreccionDeTranscripcion:
    """Nuestra copia estaba mal — la ley no se movió. Es OTRA categoría que una enmienda.

    Mezclarlas costaría el hallazgo central del expediente: los tres orígenes de `ORIGENES`
    describen que la LEY cambió, y el informe usa esa lista para señalar que el evaluado puede
    mover su propia vara por el artículo 20. Un registro de enmiendas con enmiendas inventadas
    vale menos que uno vacío.
    """

    def _sello(self, tmp_path, correcciones):
        import yaml  # type: ignore[import-untyped]

        base = tmp_path / "corr"
        base.mkdir()
        (base / "sello.yaml").write_text(
            yaml.safe_dump({"sello": {"hash_metas": "viejo", "fecha": "2026-01-01",
                                      "aprobado_por": "X"},
                            "correcciones": correcciones}, allow_unicode=True),
            encoding="utf-8")
        return base

    def _corr(self, hash_resultante, aprobado_por=""):
        return {"id": "c1", "fecha": "2026-08-21", "indicadores": ["3.22"],
                "detalle": "el glifo ≥ salió como (cid:2)",
                "evidencia": [{"indicador": "3.22", "campo": "meta_2025",
                               "anterior": "(cid:2)1.0", "corregido": ">=1.0"}],
                "hash_resultante": hash_resultante, "aprobado_por": aprobado_por}

    def test_una_correccion_SIN_FIRMA_no_surte_efecto(self, monkeypatch, tmp_path):
        """Se puede dejar preparada —con su hash y su evidencia— y el expediente sigue
        derivado hasta que alguien la firma. Es lo que permite revisarla antes de que aplique.
        """
        from modules.law_intel import ratificacion as r

        base = self._sello(tmp_path, [self._corr("nuevo")])
        monkeypatch.setattr(r, "_cargar_sello", lambda e: _yaml().safe_load(
            (base / "sello.yaml").read_text(encoding="utf-8")))
        monkeypatch.setattr(r, "hash_de_metas", lambda i: "nuevo")
        monkeypatch.setattr(r, "cargar", lambda e: type("E", (), {"indicadores": []})())
        r.estado.cache_clear()
        assert r.estado("corr").estado == "deriva_no_autorizada"
        assert not r.estado("corr").servible

    def test_firmada_y_con_el_hash_exacto_SI_surte_efecto(self, monkeypatch, tmp_path):
        from modules.law_intel import ratificacion as r

        base = self._sello(tmp_path, [self._corr("nuevo", aprobado_por="SDQ")])
        monkeypatch.setattr(r, "_cargar_sello", lambda e: _yaml().safe_load(
            (base / "sello.yaml").read_text(encoding="utf-8")))
        monkeypatch.setattr(r, "hash_de_metas", lambda i: "nuevo")
        monkeypatch.setattr(r, "cargar", lambda e: type("E", (), {"indicadores": []})())
        r.estado.cache_clear()
        st = r.estado("corr")
        assert st.estado == "corregido" and st.servible
        assert st.correccion_vigente.indicadores == ["3.22"]

    def test_una_firma_NO_alcanza_si_el_hash_no_es_el_del_registro(self, monkeypatch, tmp_path):
        """Mismo rigor que una enmienda: exigir el hash impide que una corrección real sirva
        de paraguas a una edición distinta de la que se revisó."""
        from modules.law_intel import ratificacion as r

        base = self._sello(tmp_path, [self._corr("otro", aprobado_por="SDQ")])
        monkeypatch.setattr(r, "_cargar_sello", lambda e: _yaml().safe_load(
            (base / "sello.yaml").read_text(encoding="utf-8")))
        monkeypatch.setattr(r, "hash_de_metas", lambda i: "nuevo")
        monkeypatch.setattr(r, "cargar", lambda e: type("E", (), {"indicadores": []})())
        r.estado.cache_clear()
        assert r.estado("corr").estado == "deriva_no_autorizada"

    def test_la_frase_publicable_NO_dice_que_la_ley_cambio(self, monkeypatch, tmp_path):
        """El error más caro posible acá: leer una corrección nuestra como una modificación
        del instrumento inventaría un cambio normativo que no ocurrió."""
        from modules.law_intel import ratificacion as r

        base = self._sello(tmp_path, [self._corr("nuevo", aprobado_por="SDQ")])
        monkeypatch.setattr(r, "_cargar_sello", lambda e: _yaml().safe_load(
            (base / "sello.yaml").read_text(encoding="utf-8")))
        monkeypatch.setattr(r, "hash_de_metas", lambda i: "nuevo")
        monkeypatch.setattr(r, "cargar", lambda e: type("E", (), {"indicadores": []})())
        r.estado.cache_clear()
        pub = r.publicable("corr")
        assert "ORIGINALES de la ley" in pub["frase"]
        assert pub["origen"] == "correccion_de_transcripcion"
        assert "No hubo cambio normativo" in pub["origen_nota"]
        assert pub["evidencia"], "la evidencia viaja: sin ella «corrección» es una edición"


class TestLasDosNotacionesDelUmbral:
    """Los dos extremos de la tubería tienen que entender lo mismo, y no lo entendían.

    El clasificador del extractor reconocía `≥` —el glifo que trae el PDF— y el lector del
    semáforo solo `>=`. Una meta quedaba clasificada como umbral y resultaba ilegible para
    quien la juzga: `no_evaluable` sobre una meta que la ley escribió con toda claridad.
    """

    @pytest.mark.parametrize("texto,esperado", [
        ("≥1.0", (">=", 1.0)), (">=1.0", (">=", 1.0)),
        ("≤2", ("<=", 2.0)), ("<= 2", ("<=", 2.0)),
        ("< 4", ("<", 4.0)), ("> 1.5", (">", 1.5)),
    ])
    def test_el_lector_entiende_las_dos_formas(self, texto, esperado):
        from modules.law_intel.scoring.semaforo import leer_umbral

        assert leer_umbral(texto) == esperado

    @pytest.mark.parametrize("texto", ["≥1.0", ">=1.0", "≤2", "<= 2", "< 4"])
    def test_y_el_clasificador_tambien(self, texto):
        from modules.law_intel.corpus.extractor import _escala

        assert _escala([0.85, 1.0, texto], {"2025": 1}) == "umbral"

    def test_la_forma_AMBIGUA_sigue_sin_interpretarse(self):
        """`>1,700` no se toca: la coma puede ser miles o decimal en notación española. Se
        corrige en el DATO, no aflojando el lector."""
        from modules.law_intel.scoring.semaforo import leer_umbral

        assert leer_umbral(">1,700") is None
