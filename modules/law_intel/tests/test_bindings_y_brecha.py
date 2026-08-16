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


class TestTransformacionDeclarada:
    """El indicador 2.19 es ANALFABETISMO y la variable es alfabetización.

    Sin declarar la transformación el binding publicaría el complemento — el valor invertido.
    Y la transformación es un nombre de un conjunto CERRADO, no una fórmula: una expresión
    libre en un archivo de datos es código sin revisar, y acá decide qué cifra se publica.
    """

    def test_aplica_el_complemento(self):
        from modules.law_intel.bindings import aplicar_transformacion
        b = Binding("2.19", "s", "one", "menor", "propuesto", transformacion="complemento_100")
        assert aplicar_transformacion(b, 93.7) == pytest.approx(6.3)

    def test_sin_transformacion_el_valor_pasa_intacto(self):
        from modules.law_intel.bindings import aplicar_transformacion
        assert aplicar_transformacion(Binding("x", "s", "one", "mayor", "propuesto"), 9.6) == 9.6

    def test_una_formula_libre_no_carga(self):
        from modules.law_intel.registro import Expediente
        e = Expediente(id="t", titulo="t", norma="t",
                       meta={"fuentes_admitidas": [{"id": "one", "nombre": "ONE"}]},
                       indicadores=[Indicador(id="1.8", eje=1, nombre="x", escala="numerica",
                                              base_valor=24.8, metas={"2030": 4.0})])
        with pytest.raises(ExpedienteInvalido, match="fórmulas libres"):
            _validar(e, [Binding("1.8", "s", "one", "menor", "propuesto",
                                 transformacion="100 - x")])


class TestLasCuatroDudasResueltas:
    """Cada resolución se comprobó contra lo que el panel declara medir, no contra el nombre."""

    def test_poverty_rate_va_al_indicador_general_no_al_extremo(self):
        """`_THEME_LABELS` del panel dice «Pobreza monetaria general» y el valor es 15,0.
        El 2.1 es pobreza EXTREMA (meta 3,5% en 2025); el 2.4 es la moderada."""
        bs = cargar_bindings(EXPEDIENTE)
        assert bs["2.4"].serie == "social_dev:poverty_rate"
        assert not (bs["2.4"].nota_comparabilidad or "").strip(), "la duda quedó resuelta"

    def test_el_indicador_de_pobreza_extrema_declara_su_brecha_real(self):
        """El dato EXISTE en la plataforma y no está expuesto donde la verificación lo
        alcanza. Es una brecha nuestra de superficie, no una duda sobre qué mide."""
        b = cargar_bindings(EXPEDIENTE)["2.1"]
        assert b.serie == "social_dev:poverty_extreme"
        assert "no se expone" in (b.nota_comparabilidad or "").lower()

    def test_analfabetismo_lleva_su_transformacion(self):
        b = cargar_bindings(EXPEDIENTE)["2.19"]
        assert b.transformacion == "complemento_100"
        assert not (b.nota_comparabilidad or "").strip()

    def test_el_ingreso_queda_descartado_con_su_motivo(self):
        b = cargar_bindings(EXPEDIENTE)["3.26"]
        assert b.estado == "descartado"
        m = b.motivo_descarte or ""
        assert "MENSUAL" in m and "Atlas" in m, "el motivo nombra las dos magnitudes"

    def test_las_resueltas_ya_no_bloquean(self):
        """Ninguna de las tres resueltas conserva una duda abierta."""
        bs = cargar_bindings(EXPEDIENTE)
        for i in ("2.4", "2.19", "2.18", "2.21"):
            assert not (bs[i].nota_comparabilidad or "").strip(), i
