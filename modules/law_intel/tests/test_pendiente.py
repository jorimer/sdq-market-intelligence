"""Las metas que todavía no vencen.

El caso que ordena todo el módulo: **una meta pendiente no se puede incumplir**. Correr el
semáforo con el corte movido al horizonte devolvía `no_alcanzada` sobre metas que vencen
dentro de cinco años, y publicar eso sería el reflejo exacto del eufemismo que este producto
denuncia — con el signo cambiado.
"""
import pytest

from modules.law_intel.bindings import Binding
from modules.law_intel.registro import Indicador
from modules.law_intel.scoring.pendiente import (DEPENDEN_DEL_RITMO, ESTADOS, evaluar,
                                                 horizonte_de, panel, publicable, resumen)
from modules.law_intel.scoring.semaforo import evaluar as evaluar_vencida


def _ind(metas, escala="numerica") -> Indicador:
    return Indicador(id="2.1", eje=2, nombre="Un indicador", escala=escala,
                     base_anio=2010, metas=metas)


def _binding(mejor="mayor") -> Binding:
    return Binding(indicador="2.1", serie="serie.x", fuente="una_fuente",
                   mejor=mejor, estado="verificado")


class TestUnaMetaPendienteNoSePuedeINCUMPLIR:
    def test_ningun_estado_del_vocabulario_afirma_incumplimiento(self):
        for estado, glosa in ESTADOS.items():
            for prohibida in ("incumpl", "no alcanzó", "falló", "fracas"):
                assert prohibida not in (estado + " " + glosa).lower(), (
                    f"«{estado}» adelanta un juicio de incumplimiento sobre una meta que no "
                    f"venció")

    def test_UNA_sola_observacion_no_produce_veredicto_de_incumplimiento(self):
        """El defecto que este módulo evita. Con el corte movido al horizonte, el semáforo
        devuelve `no_alcanzada` sobre una meta de 2030: dice que ya falló algo que todavía
        tiene cinco años por delante."""
        ind = _ind({"2025": 50.0, "2030": 80.0})
        obs = [("2024", 40.0)]
        del_semaforo = evaluar_vencida(ind, _binding(), obs, "2030")
        assert del_semaforo.veredicto == "no_alcanzada"          # lo que NO se publica

        de_lo_pendiente = evaluar(ind, _binding(), obs, "2030")
        assert de_lo_pendiente.estado == "sin_trayectoria"
        assert de_lo_pendiente.falta == 40.0                     # la distancia SÍ se dice


class TestElRitmoSeCOMPARAconElPLAZO:
    def test_al_ritmo_observado_LLEGA_antes_del_horizonte(self):
        """El veredicto que el semáforo declara en su vocabulario y nunca emite."""
        ind = _ind({"2030": 80.0})
        obs = [("2020", 40.0), ("2024", 60.0)]        # 5 por año, faltan 20, quedan 6 años
        p = evaluar(ind, _binding(), obs, "2030")
        assert p.estado == "en_trayectoria"
        assert p.ritmo_por_anio == 5.0 and p.anios_restantes == 6

    def test_al_ritmo_observado_NO_llega(self):
        ind = _ind({"2030": 80.0})
        obs = [("2020", 40.0), ("2024", 44.0)]        # 1 por año, faltan 36, quedan 6
        p = evaluar(ind, _binding(), obs, "2030")
        assert p.estado == "no_llegara_al_ritmo_actual"
        assert "quedan 6 años" in p.motivo and "36" in p.motivo

    def test_el_motivo_dice_CUANTOS_ANIOS_pediria_la_meta(self):
        """«le faltan 36 al ritmo de 1 por año» es una decisión; «no llegará» es un adjetivo."""
        ind = _ind({"2030": 80.0})
        p = evaluar(ind, _binding(), [("2020", 40.0), ("2024", 44.0)], "2030")
        assert "36.0 años de recorrido" in p.motivo

    def test_el_ritmo_sale_de_la_serie_ENTERA_y_no_de_los_dos_ULTIMOS_puntos(self):
        """Un rebote de un año no decide el veredicto de una década. Los dos últimos puntos
        dan 20 por año; la serie entera da 5, que es lo que realmente pasó."""
        ind = _ind({"2030": 80.0})
        obs = [("2020", 40.0), ("2021", 42.0), ("2022", 44.0), ("2023", 40.0), ("2024", 60.0)]
        p = evaluar(ind, _binding(), obs, "2030")
        assert p.ritmo_por_anio == 5.0 and p.desde == "2020"

    def test_dos_observaciones_del_MISMO_anio_no_producen_pendiente(self):
        ind = _ind({"2030": 80.0})
        p = evaluar(ind, _binding(), [("2024", 40.0), ("2024", 44.0)], "2030")
        assert p.estado == "sin_trayectoria"

    def test_un_horizonte_que_ya_paso_no_se_proyecta(self):
        ind = _ind({"2020": 80.0})
        p = evaluar(ind, _binding(), [("2018", 40.0), ("2024", 50.0)], "2020")
        assert p.estado == "sin_trayectoria"
        assert "no hay plazo que proyectar" in p.motivo


class TestLosOtrosEstados:
    def test_el_dato_de_hoy_ya_cumple_la_meta_del_horizonte(self):
        p = evaluar(_ind({"2030": 80.0}), _binding(), [("2020", 70.0), ("2024", 85.0)], "2030")
        assert p.estado == "ya_alcanzada" and "sostenerlo" in p.motivo

    def test_se_aleja(self):
        p = evaluar(_ind({"2030": 80.0}), _binding(), [("2020", 60.0), ("2024", 50.0)], "2030")
        assert p.estado == "se_aleja"

    def test_no_se_mueve_NO_se_redacta_como_que_se_aleja(self):
        p = evaluar(_ind({"2030": 80.0}), _binding(), [("2020", 60.0), ("2024", 60.0)], "2030")
        assert p.estado == "no_se_mueve"
        assert "se aleja" not in p.motivo and "en contra" not in p.motivo

    def test_la_direccion_de_mejora_la_da_el_BINDING(self):
        """En un indicador donde menos es mejor, bajar es avanzar."""
        p = evaluar(_ind({"2030": 2.0}), _binding("menor"),
                    [("2020", 10.0), ("2024", 6.0)], "2030")
        assert p.ritmo_por_anio == 1.0 and p.estado == "en_trayectoria"

    def test_sin_meta_al_horizonte(self):
        p = evaluar(_ind({"2025": 50.0}), _binding(), [("2024", 40.0)], "2030")
        assert p.estado == "sin_meta_al_horizonte"

    def test_sin_binding_verificado_no_hay_proyeccion(self):
        b = Binding(indicador="2.1", serie="serie.x", fuente="una_fuente",
                    mejor="mayor", estado="propuesto")
        assert evaluar(_ind({"2030": 80.0}), b, [("2024", 40.0)], "2030").estado == "sin_medicion"

    def test_una_meta_de_escala_que_no_se_resta_se_DECLARA(self):
        ind = _ind({"2030": "< 4"}, escala="umbral")
        assert evaluar(ind, _binding(), [("2024", 5.0)], "2030").estado == "no_evaluable"

    def test_una_escala_ORDINAL_no_se_proyecta_aunque_la_meta_sea_un_numero(self):
        """El guard cruzado: el semáforo se niega a restar una posición, y esta superficie
        tenía que negarse igual. Mirar solo el tipo de la celda las habría hecho discrepar."""
        ind = _ind({"2030": 12.0}, escala="ordinal")
        assert evaluar(ind, _binding(), [("2020", 30.0), ("2024", 20.0)], "2030").estado == (
            "no_evaluable")

    @pytest.mark.parametrize("escala", ["numerica", "redactada", "ordinal", "umbral",
                                        "sin_meta"])
    def test_NINGUNA_escala_se_proyecta_si_el_semaforo_la_declara_no_evaluable(self, escala):
        """Las cinco escalas que el registro de la END usa hoy, cruzadas contra los dos
        motores. Si el semáforo no la juzga, lo pendiente tampoco la proyecta."""
        ind = _ind({"2030": 80.0}, escala=escala)
        obs = [("2020", 40.0), ("2024", 60.0)]
        if evaluar_vencida(ind, _binding(), obs, "2030").veredicto == "no_evaluable":
            assert evaluar(ind, _binding(), obs, "2030").estado == "no_evaluable", (
                f"la escala '{escala}' se proyecta acá y el semáforo la rechaza")


class TestElHORIZONTEsaleDeLaLEY:
    def test_lo_declara_el_expediente_y_no_el_codigo(self):
        assert horizonte_de({"vigencia_hasta": "2030-12-31"}) == "2030"
        assert horizonte_de({"vigencia_hasta": "2036-12-31"}) == "2036"

    def test_sin_vigencia_declarada_devuelve_None_en_vez_de_suponer(self):
        assert horizonte_de({}) is None
        assert horizonte_de({"vigencia_hasta": "sin fecha"}) is None

    def test_NINGUN_anio_esta_escrito_en_el_modulo(self):
        """Un 2030 en el código volvería el producto un evaluador de una sola norma."""
        import re
        from pathlib import Path
        fuente = Path("modules/law_intel/scoring/pendiente.py").read_text(encoding="utf-8")
        codigo = "\n".join(linea for linea in fuente.splitlines()
                           if not linea.strip().startswith(("#", '"', "'")))
        # Los años que aparecen en docstrings y comentarios son ejemplos; en CÓDIGO, ninguno.
        assert not re.findall(r"[\"'](?:20\d\d)[\"']", codigo)


class TestLoQueViajaAlModelo:
    def test_la_regla_prohibe_el_vocabulario_de_incumplimiento(self):
        pub = publicable([], "2030")
        assert "no se puede incumplir" in pub["regla_de_lo_pendiente"].lower()

    def test_los_estados_que_dependen_del_ritmo_estan_NOMBRADOS(self):
        """Para que el renderizador exija el supuesto sin tener que acordarse."""
        assert set(DEPENDEN_DEL_RITMO) == {"en_trayectoria", "no_llegara_al_ritmo_actual"}
        p = evaluar(_ind({"2030": 80.0}), _binding(), [("2020", 40.0), ("2024", 60.0)], "2030")
        assert p.depende_del_ritmo

    def test_las_metas_sin_horizonte_no_ensucian_la_tabla_pero_SI_el_resumen(self):
        inds = [_ind({"2030": 80.0}), Indicador(id="2.2", eje=2, nombre="Otro",
                                                escala="numerica", metas={"2025": 10.0})]
        bs = {"2.1": _binding()}
        ps = panel(inds, bs, {"serie.x": [("2020", 40.0), ("2024", 60.0)]}, "2030")
        pub = publicable(ps, "2030")
        filas = pub["metas_pendientes_al_horizonte_de_la_ley"]["por_indicador"]
        assert [f["indicador"] for f in filas] == ["2.1"]
        r = resumen(ps)
        assert r["total_indicadores"] == 2 and r["con_meta_al_horizonte"] == 1

    def test_el_resumen_separa_lo_proyectable_del_total(self):
        ps = [evaluar(_ind({"2030": 80.0}), _binding(), [("2020", 40.0), ("2024", 60.0)], "2030"),
              evaluar(_ind({"2030": 80.0}), None, [], "2030")]
        r = resumen(ps)
        assert r["proyectables"] == 1 and r["en_trayectoria"] == 1
        assert r["total_indicadores"] == 2


def test_el_panel_recorre_toda_la_ley():
    inds = [_ind({"2030": 80.0}),
            Indicador(id="3.1", eje=3, nombre="Otro", escala="numerica",
                      metas={"2030": 5.0})]
    ps = panel(inds, {"2.1": _binding()}, {"serie.x": [("2020", 40.0), ("2024", 60.0)]}, "2030")
    assert [p.indicador for p in ps] == ["2.1", "3.1"]
    assert ps[1].estado == "sin_medicion"


@pytest.mark.parametrize("estado", list(ESTADOS))
def test_todo_estado_declarado_tiene_glosa_no_vacia(estado):
    assert ESTADOS[estado].strip()
