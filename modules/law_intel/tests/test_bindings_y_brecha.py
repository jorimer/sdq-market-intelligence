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
                     [Binding("1.8", "s", "one", "mayor", "verificado", periodo_verificado="2024")])

    def test_fuente_fuera_de_la_lista_blanca(self):
        with pytest.raises(ExpedienteInvalido, match="lista blanca"):
            _validar(self._exp_falso(),
                     [Binding("1.8", "s", "banco-mundial", "menor", "verificado", periodo_verificado="2024")])

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
            _validar(self._exp_falso(), [Binding("9.9", "s", "one", "menor", "verificado", periodo_verificado="2024")])

    def test_binding_duplicado(self):
        with pytest.raises(ExpedienteInvalido, match="duplicado"):
            _validar(self._exp_falso(), [Binding("1.8", "s", "one", "menor", "verificado")] * 2)

    def test_direccion_plana_no_bloquea(self):
        """Con metas planas la dirección no es deducible; el binding decide y no se contradice."""
        e = self._exp_falso(base_valor=24.4, metas={"2015": 24.4, "2030": 24.4})
        _validar(e, [Binding("1.8", "s", "one", "mayor", "verificado", periodo_verificado="2024")])


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
        # 2.4 volvió a tener nota ABIERTA, pero por OTRA razón: la duda original (¿general
        # o extrema?) sí quedó resuelta, y lo que la frena hoy es que la variable se mide
        # por región. Se comprueba el motivo, no la ausencia — si no, el test pasaría
        # también si alguien reabriera la duda vieja.
        assert "REGIÓN" in (bs["2.4"].nota_comparabilidad or "").upper()

    def test_la_pobreza_extrema_NO_puede_medirse_con_una_cifra_regional(self):
        """La brecha era NUESTRA —el tema estaba ingerido y no se exponía como señal— y se
        cerró exponiéndolo (PR #748). Verificado en prod: 2,0% en 2024.

        Lo que el test protege ahora no es el estado sino la salvedad: este indicador alcanza
        la meta de 2030 seis años antes, y publicarlo sin declarar que la línea base legal es
        ENFT-2010 y la medición es ENCFT/ENGIH con metodología cambiada en 2022 sería el
        mismo defecto que el instrumento denuncia."""
        b = cargar_bindings(EXPEDIENTE)["2.1"]
        assert b.serie == "social_dev:poverty_extreme"
        # Se expuso el tema (PR #748) y aun así NO puede contar: `poverty_extreme` se mide
        # por región y el registro publica el valor de la primera. El 2,0% que se llegó a
        # publicar como «meta de 2030 alcanzada seis años antes» era de `cibao_norte`.
        assert not b.cuenta
        assert "REGIÓN" in (b.nota_comparabilidad or "").upper()
        assert "2022" in (b.nota or ""), "el corte metodológico no puede quedar sin declarar"

    def test_analfabetismo_lleva_su_transformacion(self):
        b = cargar_bindings(EXPEDIENTE)["2.19"]
        assert b.transformacion == "complemento_100"
        # Su nota abierta es la del alcance regional, no la de la transformación: la
        # dirección quedó resuelta y declarada.
        assert "REGIÓN" in (b.nota_comparabilidad or "").upper()

    def test_el_ingreso_queda_descartado_con_su_motivo(self):
        b = cargar_bindings(EXPEDIENTE)["3.26"]
        assert b.estado == "descartado"
        m = b.motivo_descarte or ""
        assert "MENSUAL" in m and "Atlas" in m, "el motivo nombra las dos magnitudes"

    def test_las_dudas_de_COMPARABILIDAD_originales_quedaron_resueltas(self):
        """Las cuatro dudas de 2026-08-16 eran sobre QUÉ MIDE cada variable, y esas se
        cerraron. Las que hoy bloquean a 2.4, 2.18 y 2.19 son de ALCANCE —la variable mide
        una región, no el país— y son otra cosa.

        El test comprueba el MOTIVO y no la ausencia: exigir que no haya nota lo hacía
        fallar cuando apareció un impedimento distinto y legítimo, que es romperse por
        avanzar."""
        bs = cargar_bindings(EXPEDIENTE)
        assert not (bs["2.21"].nota_comparabilidad or "").strip()
        # 2.18 salió de la lista: se recuperó apuntando a la cifra nacional del SISDOM.
        for i in ("2.4", "2.19"):
            nota = (bs[i].nota_comparabilidad or "").upper()
            assert "REGIÓN" in nota, f"{i} bloquea por un motivo que no es el de alcance"
        assert bs["2.18"].cuenta, "2.18 se recuperó con la serie nacional"


class TestLasSenalesQueYaEstabanExpuestas:
    """Tres indicadores que no exigían conectar nada: la señal ya estaba en el Data Registry
    sirviendo al índice de desarrollo y ningún binding la había cruzado contra la ley.

    Los tres muestran la misma trampa en tres grados distintos, y por eso van juntos: el
    nombre de la variable se parece al del indicador en los tres casos, y solo en uno miden
    lo mismo."""

    def test_las_coberturas_educativas_apuntan_a_la_cifra_del_PAIS(self):
        """Empezaron atadas a la serie por región —que servía cibao_norte— y se repuntaron
        a la fila `TOTAL PAIS` del tablero. El sufijo `_pais` es lo que distingue una de
        otra, así que el test lo exige explícitamente."""
        bs = cargar_bindings(EXPEDIENTE)
        for ind, esperada in (("2.9", "social_dev:primary_coverage_pais"),
                              ("2.10", "social_dev:secondary_coverage_pais")):
            assert bs[ind].serie == esperada
            assert bs[ind].transformacion is None, "misma magnitud: nada que transformar"

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


class TestLaFrescuraDeclarada:
    """Sin período declarado el producto no tiene frescura, y el readiness castiga eso con
    un factor 0,5 — un «no aplica» honesto puntuaba igual que un dato medio rancio. El
    período se declara al promover, que es cuando se conoce."""

    def test_no_se_puede_promover_un_binding_sin_declarar_su_periodo(self):
        with pytest.raises(ExpedienteInvalido) as e:
            _validar(cargar(EXPEDIENTE),
                     [Binding(indicador="2.1", serie="social_dev:poverty_extreme",
                              fuente="one", mejor="menor", estado="verificado")])
        assert "periodo_verificado" in str(e.value)

    def test_los_verificados_del_expediente_declaran_su_periodo(self):
        for b in cargar_bindings(EXPEDIENTE).values():
            if b.cuenta:
                assert (b.periodo_verificado or "").strip(), b.indicador

    def test_la_antiguedad_es_la_del_dato_MAS_VIEJO(self):
        """Tomar el más nuevo diría «datos de 2024» aunque medio panel fuera de 2019. Un
        informe es tan actual como su componente más rancio."""
        import datetime as dt

        from modules.law_intel.products import _antiguedad_del_dato
        dias = _antiguedad_del_dato(EXPEDIENTE)
        anios = sorted(int((b.periodo_verificado or "0")[:4])
                       for b in cargar_bindings(EXPEDIENTE).values() if b.cuenta)
        esperado = (dt.date.today() - dt.date(anios[0], 12, 31)).days
        assert dias == max(0, esperado)

    def test_un_expediente_sin_verificados_no_inventa_frescura(self):
        """`None` y no 0: un 0 se leería como «dato de hoy», que es lo contrario de la
        verdad cuando no hay ningún dato."""
        from modules.law_intel.products import _antiguedad_del_dato
        # `meta_rd_2036` está cargado como segundo expediente y no tiene bindings.
        assert _antiguedad_del_dato("meta_rd_2036") is None

    def test_la_frescura_declarada_le_devuelve_al_producto_el_factor_entero(self):
        """El punto de todo esto: sin período el readiness multiplicaba la cobertura por
        0,5, así que cada indicador medido rendía la mitad. Con 2024 declarado y cadencia
        anual (pleno hasta dos años), el factor es 1,0 y `pulse` pasa a exigir 15 de 90 en
        vez de 30."""
        from shared.products.readiness import _freshness_factor
        from modules.law_intel.products import _antiguedad_del_dato
        assert _freshness_factor(_antiguedad_del_dato(EXPEDIENTE), "annual") == 1.0


class TestMercadoLaboral:
    """Los tres indicadores salen del MISMO libro del BCRD y no tienen la misma calidad de
    evidencia. La diferencia es el hallazgo, no un detalle de implementación."""

    def test_el_NIVEL_de_desocupacion_no_es_evaluable_contra_su_meta(self):
        """La base legal es ENFT-2010 (14,3%) y la medición es ENCFT, que arranca en 7,33%.
        El nivel se parte casi al medio en el momento del cambio de encuesta, no de la
        política. Publicar «meta superada» sería exactamente la mentira que este módulo
        existe para no cometer."""
        b = cargar_bindings(EXPEDIENTE)["2.37"]
        assert not b.cuenta, "un nivel no comparable no puede contar como cobertura"
        nota = (b.nota_comparabilidad or "").upper()
        assert "ENFT" in nota and "ENCFT" in nota, "la nota nombra las dos encuestas"

    def test_pero_las_RAZONES_si_son_evaluables(self):
        """Una razón entre dos poblaciones medidas con la misma encuesta es robusta al
        cambio de metodología: se cancela en numerador y denominador. Por eso las brechas
        de género sobreviven donde el nivel no."""
        for ind in ("2.41", "2.42"):
            b = cargar_bindings(EXPEDIENTE)[ind]
            assert not b.nota_comparabilidad, f"{ind} no debería estar bloqueado"

    def test_las_dos_brechas_apuntan_en_sentidos_OPUESTOS(self):
        """La de ocupación mejora subiendo hacia la paridad y la de desocupación mejora
        bajando. Copiarle la dirección a la otra invertiría el veredicto — y acá el
        validador lo atajaría contra las metas de la ley, que es el punto."""
        bs = cargar_bindings(EXPEDIENTE)
        assert bs["2.41"].mejor == "mayor"
        assert bs["2.42"].mejor == "menor"


def test_ningun_binding_que_CUENTA_se_apoya_en_una_variable_por_region():
    """La regla que faltaba, escrita como invariante del expediente y no como lista.

    Cinco bindings llegaron a producción contrastando el valor de `cibao_norte` contra una
    meta nacional. El guard vive en el proveedor —rechaza lo que no es nacional— y esto
    comprueba la otra mitad: que el expediente no declare como medido algo que el proveedor
    va a negarse a servir, porque eso dejaría la cobertura publicada por encima de lo que
    el informe puede sostener.
    """
    from shared.registry.builders import axis_variable_scopes

    bs = cargar_bindings(EXPEDIENTE)
    scopes = axis_variable_scopes("social")
    assert scopes, "sin la doctrina de alcances el test no probaría nada"
    por_region = []
    for b in bs.values():
        if not b.cuenta or not b.serie.startswith("social_dev:"):
            continue
        var = b.serie.split(":", 1)[1]
        if scopes.get(var, "per_subject") != "national":
            por_region.append(f"{b.indicador} → {var}")
    assert not por_region, (
        "estos bindings CUENTAN pero su variable se mide por región, así que publican el "
        f"valor de una demarcación contra una meta nacional: {por_region}"
    )


class TestUsuariosDeInternet:
    """El 3.13 es la trampa de magnitudes más fina del expediente: hay TRES cifras de
    internet en la plataforma y solo una mide lo que la ley pide."""

    def test_apunta_a_usuarios_y_no_a_suscripciones(self):
        b = cargar_bindings(EXPEDIENTE)["3.13"]
        assert b.serie == "social_dev:internet_users"
        nota = (b.nota or "").lower()
        # La nota nombra las dos magnitudes que NO son, porque el error se comete al
        # elegir, no al leer: las tres suenan igual.
        assert "banda ancha" in nota and "indotel" in nota

    def test_declara_que_la_linea_base_de_la_ley_no_coincide_con_la_edicion_vigente(self):
        """26,8% dice la ley para 2009; 27,72% dice el WDI hoy. Es revisión estadística,
        no desempeño — y medir la distancia a la meta sin decirlo atribuye a la política
        una diferencia que puso el revisor."""
        b = cargar_bindings(EXPEDIENTE)["3.13"]
        assert "26,8" in (b.nota or "") and "27,72" in (b.nota or "")


def test_ningun_binding_declara_una_fuente_que_no_sea_la_que_lo_produce():
    """`2.21` decía `fuente: one` y su dato viene del WDI. Un rótulo de procedencia falso
    es peor que uno ausente, porque se cita: el informe genera la prosa de fuentes desde
    acá.

    Se comprueba lo comprobable sin adivinar: los bindings cuya serie es del panel social
    y cuyo dato ingiere el sync desde el WDI tienen que declararlo."""
    from modules.social_dev.social_sync import WDI_HEALTH, WDI_NACIONALES_FUERA_DEL_INDICE

    del_wdi = set(WDI_HEALTH.values()) | {t for t, _u in WDI_NACIONALES_FUERA_DEL_INDICE.values()}
    mal = []
    for b in cargar_bindings(EXPEDIENTE).values():
        if not b.serie.startswith("social_dev:"):
            continue
        if b.serie.split(":", 1)[1] in del_wdi and b.fuente != "wdi":
            mal.append(f"{b.indicador} → {b.serie} declara `{b.fuente}`")
    assert not mal, f"la procedencia declarada no es la real: {mal}"
