"""El motor de Research tiene que VER el cruce socio × capítulo.

El 2026-08-13 un informe a medida respondió que el desglose de importaciones desde China
"excede lo que los motores disponibles pueden responder", e INFIRIÓ la composición ("bienes de
consumo masivo, insumos industriales… son categorías plausibles"). El dato existía a una
llamada de Comtrade; después se ingirió y se expuso, y el motor SEGUÍA sin verlo porque
`_trade_summary` sólo leía `payload["score"]`.
"""
from shared.research.data_pull import _trade_summary

_PAYLOAD = {
    "score": {"resilience_score": 67.3, "import_dependency": 0.7,
              "total_exports": 4184.7, "total_imports": 8547.5},
    "socios_por_capitulo": {
        "China": {
            "period": "2025", "total_usd_mm": 5988.0, "n_capitulos": 94,
            "capitulos_top": [{"capitulo": "85", "usd_mm": 1040.0, "pct": 17.4},
                              {"capitulo": "84", "usd_mm": 946.0, "pct": 15.8}],
            "truncado": 92, "fuente": "UN Comtrade",
        }
    },
}


def _textos(payload):
    return " ".join(e.text for e in _trade_summary("RD", payload, "2026-Q2", "trade"))


def test_el_desglose_por_socio_llega_como_evidencia():
    t = _textos(_PAYLOAD)
    assert "China" in t and "5,988" in t.replace(".", ",") or "5988" in t.replace(",", "")
    assert "cap. 85" in t and "94 capítulos" in t


def test_el_sujeto_viaja_con_el_numero():
    """Cada línea nombra al socio: sin eso el modelo reatribuye la cifra al total del país,
    que es exactamente el error que produjo «cuatro compañías concentran el 87,1%»."""
    for e in _trade_summary("RD", _PAYLOAD, "2026-Q2", "trade"):
        if "cap. 85" in e.text:
            assert "China" in e.text
            break
    else:
        raise AssertionError("no se emitió la evidencia de capítulos")


def test_el_recorte_no_es_silencioso():
    """Un top-N sin avisar se lee como si fuera la corriente entera."""
    assert "92 capítulos más no listados" in _textos(_PAYLOAD)


def test_sin_el_cruce_el_motor_no_inventa_nada():
    """Sin el dato, ninguna evidencia habla de composición por bien: la brecha queda visible
    y el modelo tiene que declararla en vez de inferir 'categorías plausibles'."""
    solo_score = {"score": _PAYLOAD["score"]}
    t = _textos(solo_score)
    assert "cap." not in t and "China" not in t
    assert "resiliencia" in t          # lo que sí hay se sigue sirviendo


def test_un_socio_sin_capitulos_no_emite_linea_vacia():
    p = {"score": _PAYLOAD["score"],
         "socios_por_capitulo": {"Vietnam": {"period": "2025", "capitulos_top": []}}}
    assert "Vietnam" not in _textos(p)


def test_la_cobertura_se_declara_en_POSITIVO():
    """La versión anterior decía "177 orígenes más no se listan acá" y el modelo lo publicó
    como «el sistema no computa el desglose para 181 orígenes» — declaró faltante lo que sí
    existe. La cobertura va afirmada, con los conteos servidos para que no los derive."""
    p = {**_PAYLOAD, "socios_por_capitulo": {
        **_PAYLOAD["socios_por_capitulo"],
        "_cobertura": {"socios_con_desglose_computado": 192,
                       "socios_listados_en_este_payload": 1, "nota": "x"}}}
    t = _textos(p)
    assert "192 socios con desglose por capítulo computado" in t
    assert "100% del valor" in t and "no es una brecha de dato" in t.lower()
    assert "China" in t                      # y los listados siguen saliendo


def test_la_evidencia_de_cobertura_pesa_mas_que_la_generica():
    """Debe sobrevivir al corte de 3 líneas en pantalla: si no, el informe vuelve a citar
    «resiliencia 67.0» mientras el cuerpo analiza el desglose."""
    from shared.research.data_pull import _trade_summary
    p = {**_PAYLOAD, "socios_por_capitulo": {
        **_PAYLOAD["socios_por_capitulo"],
        "_cobertura": {"socios_con_desglose_computado": 192,
                       "socios_listados_en_este_payload": 1, "nota": "x"}}}
    evs = _trade_summary("RD", p, "2026-Q2", "trade")
    cob = next(e for e in evs if "Cobertura del desglose" in e.text)
    gen = next(e for e in evs if "resiliencia comercial" in e.text)
    assert cob.score > gen.score


def test_el_marcador_de_omitidos_no_se_narra_como_un_socio():
    """`_omitidos` es metadato: si se colara como socio, el informe hablaría de un país
    llamado '_omitidos' con cifras inventadas."""
    p = {**_PAYLOAD, "socios_por_capitulo": {
        **_PAYLOAD["socios_por_capitulo"], "_omitidos": {"socios_no_listados": 3}}}
    assert "_omitidos" not in _textos(p)


class TestLoQueSeVeEnPantalla:
    """El bloque de Evidencia corta en 3 líneas. El informe del 2026-08-14 citaba
    «resiliencia comercial 67.0» mientras el cuerpo analizaba el desglose por socio y capítulo:
    el round-robin respetaba el orden de INSERCIÓN y las líneas específicas iban al final."""

    def _pantalla(self):
        from shared.research.assemble import _evidence_lines
        from shared.research.data_pull import _trade_summary
        p = {**_PAYLOAD, "socios_por_capitulo": {
            **_PAYLOAD["socios_por_capitulo"],
        "_cobertura": {"socios_con_desglose_computado": 192,
                       "socios_listados_en_este_payload": 1, "nota": "x"}}}

        class SQ:
            evidence = _trade_summary("RD", p, "2026-Q2", "DGA · BCRD")
        return _evidence_lines(SQ())

    def test_el_desglose_sobrevive_al_corte(self):
        """Y va PRIMERO: es lo que responde la pregunta. Lo genérico puede aparecer después
        si sobra cupo, pero nunca desplazándolo."""
        t = self._pantalla()
        assert "Importaciones desde China" in t
        if "resiliencia comercial" in t:
            assert t.index("Importaciones desde China") < t.index("resiliencia comercial")

    def test_la_cobertura_va_PRIMERA(self):
        """Si el lector se queda con una sola línea, tiene que ser la que impide restar dos
        conteos y publicar una brecha falsa."""
        t = self._pantalla()
        assert "Cobertura del desglose" in t
        assert t.index("Cobertura del desglose") < t.index("Importaciones desde")


class TestPeriodosEtiquetados:
    """El informe mezcló capítulos 2025 (Comtrade anual), cuotas 2023 y flujos 2026-Q2 (DGA
    trimestral) sin distinguirlos. Cada línea declara su ventana y su fuente."""

    def _evs(self):
        from shared.research.data_pull import _trade_summary
        return _trade_summary("RD", _PAYLOAD, "2026-Q2", "trade")

    def test_el_desglose_dice_que_es_anual_y_de_comtrade(self):
        e = next(x for x in self._evs() if "China" in x.text)
        assert "año 2025" in e.text and "UN Comtrade, anual" in e.text
        assert "NO es el corte trimestral" in e.text

    def test_los_flujos_dicen_que_no_son_comparables(self):
        e = next(x for x in self._evs() if "Flujos" in x.text)
        assert "2026-Q2" in e.text and "no" in e.text.lower() and "comparables" in e.text

    def test_la_resiliencia_declara_su_corte(self):
        e = next(x for x in self._evs() if "resiliencia comercial" in x.text)
        assert "corte 2026-Q2" in e.text and "trimestral" in e.text


def test_prohibe_EXPLICITAMENTE_restar_los_dos_conteos():
    """El payload publica `partners.import.n_partners` (193) y este bloque lista 12. El modelo
    restó y publicó «181 socios no tienen desglose», que es falso. La contradicción se
    reconcilia en el DATO y la instrucción viaja con la cifra."""
    p = {**_PAYLOAD, "socios_por_capitulo": {
        **_PAYLOAD["socios_por_capitulo"],
        "_cobertura": {"socios_con_desglose_computado": 192,
                       "socios_listados_en_este_payload": 1, "nota": "x"}}}
    t = _textos(p)
    assert "NO restes" in t and "n_partners" in t


def test_sin_bloque_de_cobertura_no_se_afirma_cobertura():
    """Sin el conteo servido no se inventa: la línea no se emite."""
    p = {**_PAYLOAD, "socios_por_capitulo": {k: v for k, v in
                                             _PAYLOAD["socios_por_capitulo"].items()}}
    assert "Cobertura del desglose" not in _textos(p)
