"""La comprobación corre donde están los datos y no muta el expediente."""
from modules.law_intel.bindings import Binding
from modules.law_intel.verificacion import ANTIGUEDAD_MAXIMA_ANIOS, comprobar, informe

BS = {"1.8": Binding("1.8", "s.viva", "one", "menor", "propuesto"),
      "2.1": Binding("2.1", "s.vieja", "one", "menor", "propuesto"),
      "3.25": Binding("3.25", "s.vacia", "mhe", "mayor", "propuesto"),
      "3.9": Binding("3.9", "s.x", "pefa", "mayor", "descartado", motivo_descarte="m")}


def proveedor(codigo):
    return {"s.viva": [("2023", 1.0), ("2024", 2.0)],
            "s.vieja": [("2011", 1.0)]}.get(codigo, [])


def test_clasifica_cada_serie():
    r = {c.indicador: c.resultado for c in comprobar(BS, proveedor, "2025")}
    assert r["1.8"] == "verificable"
    assert r["2.1"] == "congelada", "existe pero su último dato no mide el corte"
    assert r["3.25"] == "vacia"
    assert "3.9" not in r, "un binding descartado ya se evaluó; no se re-comprueba"


def test_solo_lo_verificable_promueve():
    cs = {c.indicador: c for c in comprobar(BS, proveedor, "2025")}
    assert cs["1.8"].promueve
    assert not cs["2.1"].promueve and not cs["3.25"].promueve


def test_un_proveedor_que_falla_no_rompe_el_barrido():
    def rompe(_):
        raise RuntimeError("serie caída")
    assert all(c.resultado == "vacia" for c in comprobar(BS, rompe, "2025"))


def test_el_umbral_de_antiguedad_es_el_declarado():
    justo = str(2025 - ANTIGUEDAD_MAXIMA_ANIOS)
    bs = {"1.8": Binding("1.8", "s", "one", "menor", "propuesto")}
    assert comprobar(bs, lambda _: [(justo, 1.0)], "2025")[0].resultado == "verificable"
    viejo = str(2025 - ANTIGUEDAD_MAXIMA_ANIOS - 1)
    assert comprobar(bs, lambda _: [(viejo, 1.0)], "2025")[0].resultado == "congelada"


def test_el_informe_dice_cuanta_cobertura_se_gana(monkeypatch):
    monkeypatch.setattr("modules.law_intel.verificacion.cargar_bindings", lambda _: BS)
    r = informe("x", proveedor, "2025")
    assert r["promovibles_a_verificado"] == ["1.8"]
    assert r["ganancia_de_cobertura"] == 1
    assert "NO muta el expediente" in r["nota"]


class TestExistirNoEsMedir:
    """La distinción que sostiene el módulo, y que la primera versión perdió justo en la
    función que decide qué se publica.

    El caso real: el indicador 2.19 es ANALFABETISMO y la variable del panel es
    alfabetización. La serie existe, devuelve dato de 2024, y la comprobación la daba por
    promovible. Promoverla habría publicado el complemento — el valor invertido.
    """

    CON_DUDA = {"2.19": Binding("2.19", "s.viva", "one", "menor", "propuesto",
                                nota_comparabilidad="es alfabetización, no analfabetismo")}
    LIMPIO = {"2.18": Binding("2.18", "s.viva", "one", "mayor", "propuesto")}

    def test_una_duda_declarada_frena_la_promocion(self):
        c = comprobar(self.CON_DUDA, proveedor, "2025")[0]
        assert c.existe, "la serie sí existe"
        assert c.comparabilidad_sin_resolver
        assert not c.promueve, "existir no es medir"

    def test_sin_duda_promueve(self):
        c = comprobar(self.LIMPIO, proveedor, "2025")[0]
        assert c.existe and c.promueve

    def test_el_informe_los_separa(self, monkeypatch):
        todos = {**self.CON_DUDA, **self.LIMPIO}
        monkeypatch.setattr("modules.law_intel.verificacion.cargar_bindings", lambda _: todos)
        r = informe("x", proveedor, "2025")
        assert r["promovibles_a_verificado"] == ["2.18"]
        assert r["existen_pero_con_comparabilidad_sin_resolver"] == ["2.19"]
        assert r["ganancia_de_cobertura"] == 1, "la duda no suma cobertura"

    def test_una_nota_en_blanco_no_cuenta_como_duda(self):
        bs = {"x": Binding("x", "s.viva", "one", "mayor", "propuesto", nota_comparabilidad="  ")}
        assert comprobar(bs, proveedor, "2025")[0].promueve


class TestLaFrescuraRespetaLaCADENCIA:
    """«El emisor dejó de publicar» y «el emisor publica cada seis años» son cosas opuestas, y
    un umbral fijo de 3 años las confunde.

    El caso real: las pruebas del LLECE se aplican cada ~6 años —2006, 2013, 2019, 2025 en
    curso—. Su dato de 2019 ES el más reciente que existe en el mundo, y aun así el motor lo
    marcaba `congelada` al corte de 2025, con lo que el informe habría dicho «no lo medimos»
    sobre la única medición disponible. La desnutrición infantil, en cambio, está congelada de
    verdad: la última ENDESA con esos módulos es de 2019 y NO hay reemplazo.
    """

    def _binding(self, **kw):
        from modules.law_intel.bindings import Binding
        base = dict(indicador="2.17", serie="s", fuente="llece", mejor="menor",
                    estado="verificado", periodo_verificado="2019")
        return Binding(**{**base, **kw})

    def test_sin_declarar_cadencia_rige_el_umbral_anual(self):
        """Aflojar el guard para todos sería exactamente el error que el guard evita."""
        from modules.law_intel.verificacion import ANTIGUEDAD_MAXIMA_ANIOS, ventana_de_frescura
        assert ventana_de_frescura(self._binding()) == ANTIGUEDAD_MAXIMA_ANIOS

    def test_una_prueba_hexenal_no_aparece_congelada_por_publicar_a_su_ritmo(self):
        from modules.law_intel.verificacion import ventana_de_frescura
        v = ventana_de_frescura(self._binding(cadencia_anios=6))
        assert v >= 6, "con ventana menor que la cadencia, NUNCA podría estar fresca"
        assert 2019 >= 2025 - v, "ERCE 2019 tiene que seguir viva al corte de 2025"

    def test_pero_DOS_ciclos_sin_publicar_sí_es_abandono(self):
        """El margen alcanza para un ciclo de atraso y no para dos: ahí dejar de publicar deja
        de ser cadencia y pasa a ser que el emisor abandonó la serie."""
        from modules.law_intel.verificacion import ventana_de_frescura
        v = ventana_de_frescura(self._binding(cadencia_anios=6))
        assert not (2013 >= 2025 - v), "un dato de dos ciclos atrás SÍ está congelado"

    def test_una_cadencia_anual_declarada_no_afloja_nada(self):
        from modules.law_intel.verificacion import ANTIGUEDAD_MAXIMA_ANIOS, ventana_de_frescura
        for c in (0, 1):
            assert ventana_de_frescura(self._binding(cadencia_anios=c)) == ANTIGUEDAD_MAXIMA_ANIOS
