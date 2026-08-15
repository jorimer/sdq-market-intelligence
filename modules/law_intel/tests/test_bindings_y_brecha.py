"""La cobertura no se afirma: se cuenta sobre bindings verificados, y la brecha dice de quién es."""
import pytest

from modules.law_intel.bindings import (Binding, ExpedienteInvalido, _validar, cargar_bindings,
                                        cobertura)
from modules.law_intel.registro import Indicador, cargar
from modules.law_intel.scoring.brecha import brechas, desbloqueo, resumen

EXPEDIENTE = "end_2030"


@pytest.fixture(scope="module")
def exp():
    return cargar(EXPEDIENTE)


def test_el_expediente_real_carga_sus_bindings(exp):
    bs = cargar_bindings(EXPEDIENTE)
    assert bs, "el expediente declara bindings"
    assert all(b.indicador in {i.id for i in exp.indicadores} for b in bs.values())


def test_la_cobertura_no_cuenta_propuestos():
    c = cobertura(EXPEDIENTE)
    assert c["total"] == 90
    assert c["medidos"] == 0, "hoy no hay ninguno verificado y la portada debe decirlo"
    assert c["propuestos_sin_verificar"] > 0
    assert c["pct"] == 0.0


class TestValidacionDeBindings:
    """Un binding mal declarado no llega al informe: se rechaza al cargar."""

    def _exp_falso(self, **kw):
        base = dict(id="1.8", eje=1, nombre="x", escala="numerica", base_valor=24.8,
                    metas={"2015": 20.0, "2030": 4.0})
        ind = Indicador(**{**base, **kw})
        from modules.law_intel.registro import Expediente
        return Expediente(id="t", titulo="t", norma="t",
                          meta={"fuentes_admitidas": [{"id": "one", "nombre": "ONE"}]},
                          indicadores=[ind])

    def test_direccion_invertida_no_carga(self):
        """El defecto más repetido de esta plataforma, atajado en el borde: las metas van de
        24,8 a 4,0 —menos es mejor— y el binding afirma lo contrario."""
        with pytest.raises(ExpedienteInvalido, match="invertido"):
            _validar(self._exp_falso(),
                     [Binding("1.8", "s", "one", "mayor", "verificado")])

    def test_fuente_fuera_de_la_lista_blanca(self):
        with pytest.raises(ExpedienteInvalido, match="lista blanca"):
            _validar(self._exp_falso(),
                     [Binding("1.8", "s", "banco-mundial", "menor", "verificado")])

    def test_descartado_exige_motivo(self):
        with pytest.raises(ExpedienteInvalido, match="sin motivo"):
            _validar(self._exp_falso(),
                     [Binding("1.8", "s", "cualquiera", "menor", "descartado")])

    def test_descartado_puede_citar_fuente_no_admitida(self):
        """Su razón de ser es dejar registrado qué se evaluó y por qué no sirve."""
        _validar(self._exp_falso(),
                 [Binding("1.8", "s", "wef", "menor", "descartado", motivo_descarte="x")])

    def test_binding_a_indicador_inexistente(self):
        with pytest.raises(ExpedienteInvalido, match="inexistente"):
            _validar(self._exp_falso(), [Binding("9.9", "s", "one", "menor", "verificado")])

    def test_binding_duplicado(self):
        with pytest.raises(ExpedienteInvalido, match="duplicado"):
            _validar(self._exp_falso(), [Binding("1.8", "s", "one", "menor", "verificado")] * 2)

    def test_direccion_plana_no_bloquea(self):
        """Con metas planas la dirección no es deducible; el binding decide y no se contradice."""
        e = self._exp_falso(base_valor=24.4, metas={"2015": 24.4, "2030": 24.4})
        _validar(e, [Binding("1.8", "s", "one", "mayor", "verificado")])


class TestBrecha:
    def test_clasifica_y_atribuye_responsable(self, exp):
        bs = cargar_bindings(EXPEDIENTE)
        br = brechas(exp.numerados, bs)
        tipos = {b.tipo for b in br}
        assert {"sin_binding", "binding_sin_verificar", "escala_no_medible"} <= tipos
        # Lo que no medimos por no haber conectado la fuente es NUESTRO, no del Estado.
        r = resumen(br, len(exp.numerados))
        assert r["por_responsable"]["sdq"] > 0
        assert r["por_responsable"]["instrumento"] > 0

    def test_la_escala_no_medible_no_se_le_imputa_a_nadie(self, exp):
        br = brechas(exp.numerados, cargar_bindings(EXPEDIENTE))
        for b in br:
            if b.tipo == "escala_no_medible":
                assert b.responsable == "instrumento"

    def test_el_desbloqueo_dice_cuanto_rinde_cada_accion(self, exp):
        d = desbloqueo(brechas(exp.numerados, cargar_bindings(EXPEDIENTE)))
        assert d and all(x["desbloquea"] >= 1 for x in d)
        assert d == sorted(d, key=lambda x: (-x["desbloquea"], x["accion"]))
        # Una meta redactada no la desbloquea ninguna fuente: la escala es de la ley.
        assert not any("escala" in str(x["accion"]) for x in d)

    def test_un_verificado_deja_de_ser_brecha(self, exp):
        bs = dict(cargar_bindings(EXPEDIENTE))
        bs["1.8"] = Binding("1.8", "s", "one", "menor", "verificado")
        assert "1.8" not in {b.indicador for b in brechas(exp.numerados, bs)}
