"""La cobertura no se afirma: se cuenta sobre bindings verificados, y la brecha dice de quién es."""
import pytest

from modules.law_intel.bindings import (Binding, ExpedienteInvalido, _validar, cargar_bindings,
                                        cobertura)
from modules.law_intel.registro import Indicador, cargar
from modules.law_intel.scoring.brecha import TIPOS, brechas, desbloqueo, resumen

EXPEDIENTE = "end_2030"


@pytest.fixture(scope="module")
def exp():
    return cargar(EXPEDIENTE)


def test_el_expediente_real_carga_sus_bindings(exp):
    bs = cargar_bindings(EXPEDIENTE)
    assert bs, "el expediente declara bindings"
    assert all(b.indicador in {i.id for i in exp.indicadores} for b in bs.values())


def test_la_cobertura_no_cuenta_propuestos():
    """El invariante, no la foto: `medidos` cuenta verificados y NADA más.

    La primera versión afirmaba `medidos == 0`, cierto solo mientras no hubiera ninguno
    promovido. Un test así se rompe cuando el producto avanza y empuja a actualizar el número
    sin mirar la regla.
    """
    bs = cargar_bindings(EXPEDIENTE)
    c = cobertura(EXPEDIENTE)
    verificados = {i for i, b in bs.items() if b.estado == "verificado"}
    numerados = {i.id for i in cargar(EXPEDIENTE).numerados}
    assert c["total"] == 90
    assert c["medidos"] == len(verificados & numerados)
    assert c["propuestos_sin_verificar"] == len(
        {i for i, b in bs.items() if b.estado == "propuesto"} & numerados)
    # Un descartado nunca suma, aunque su serie exista.
    assert not ({i for i, b in bs.items() if b.estado == "descartado"} & verificados)


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
        # `binding_sin_verificar` NO se exige: depende de que haya bindings `propuesto` en
        # ese momento, y hoy no queda ninguno. Exigirlo era codificar la foto del expediente
        # y no la regla — el test se rompía al AVANZAR, que es cuando menos debe romperse.
        assert {"sin_binding", "escala_no_medible"} <= tipos
        assert tipos <= set(TIPOS), "un tipo de brecha fuera del vocabulario declarado"
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

    def test_la_pobreza_extrema_quedo_medida_y_declara_su_salvedad(self):
        """La brecha era NUESTRA —el tema estaba ingerido y no se exponía como señal— y se
        cerró exponiéndolo (PR #748). Verificado en prod: 2,0% en 2024.

        Lo que el test protege ahora no es el estado sino la salvedad: este indicador alcanza
        la meta de 2030 seis años antes, y publicarlo sin declarar que la línea base legal es
        ENFT-2010 y la medición es ENCFT/ENGIH con metodología cambiada en 2022 sería el
        mismo defecto que el instrumento denuncia."""
        b = cargar_bindings(EXPEDIENTE)["2.1"]
        assert b.serie == "social_dev:poverty_extreme"
        assert b.cuenta, "la brecha de superficie está cerrada; el binding debe contar"
        assert not (b.nota_comparabilidad or "").strip()
        assert "2022" in (b.nota or ""), "el corte metodológico no puede quedar sin declarar"

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


class TestLasSenalesQueYaEstabanExpuestas:
    """Tres indicadores que no exigían conectar nada: la señal ya estaba en el Data Registry
    sirviendo al índice de desarrollo y ningún binding la había cruzado contra la ley.

    Los tres muestran la misma trampa en tres grados distintos, y por eso van juntos: el
    nombre de la variable se parece al del indicador en los tres casos, y solo en uno miden
    lo mismo."""

    def test_la_cobertura_secundaria_calza_directo(self):
        b = cargar_bindings(EXPEDIENTE)["2.10"]
        assert b.serie == "social_dev:secondary_coverage"
        assert b.transformacion is None, "misma magnitud: no hay nada que transformar"

    def test_el_sector_formal_es_el_COMPLEMENTO_de_la_informalidad(self):
        """El indicador legal cuenta el sector FORMAL; la variable mide la INFORMALIDAD.
        Sin la transformación declarada el binding publicaría el complemento y la dirección
        quedaría invertida — el mismo defecto que ya se coló una vez con el 2.19."""
        b = cargar_bindings(EXPEDIENTE)["2.39"]
        assert b.transformacion == "complemento_100"
        assert b.mejor == "mayor", "más formalidad es mejor; la variable cruda diría lo opuesto"

    def test_la_mortalidad_infantil_NO_es_la_de_menores_de_cinco(self):
        """`child_mortality` es `SP.DYN.IMRT.IN` (menores de 1 año) y el indicador legal es
        menores de 5. Ninguna transformación las convierte, y el valor es plausible para las
        dos — que es justamente lo que vuelve peligrosa la confusión."""
        b = cargar_bindings(EXPEDIENTE)["2.22"]
        assert b.estado == "descartado" and not b.cuenta
        m = b.motivo_descarte or ""
        assert "SP.DYN.IMRT.IN" in m, "el motivo debe nombrar el código que lo prueba"
        assert "1 año" in m and "5" in m, "el motivo nombra los dos tramos de edad"
