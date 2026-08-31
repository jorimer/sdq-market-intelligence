"""Un indicador que el motor declaró NO disponible no se publica con valor ni con score.

Por qué existe. El motor ya hacía lo correcto: cuando falta un insumo marca el indicador
`available=False`, lo excluye del promedio de su dimensión y renormaliza los pesos sobre lo
medido. Lo que ninguna superficie hacía era HONRAR esa marca al dibujar la tabla: leían el
`raw` —que es el 0.0 por defecto de la estructura de datos— y el `score` que la curva le da
a ese cero. Para los indicadores INVERSOS, donde menos es mejor, el cero puntúa 100.

Qué costó: el Deep Dive de Banco Múltiple Caribe Internacional al 2026-06-30 —el corte cuyo
cubo de crédito la SIB todavía no publicó— salió diciendo «Concentración top-10: 0.00% ·
score 100.0» y «HHI sectorial de cartera: 0 · score 100.0». Al cierre de 2025 la
concentración real de esa entidad era 34,90%, su peor indicador de calidad. La CALIFICACIÓN
estaba bien —54.29, con los dos excluidos—; el DOCUMENTO no, y es el documento lo que se
vende.

La fila NO se publica. Hubo una versión intermedia que la mostraba marcada «s/d» con su nota
al pie; el dueño la revirtió el 2026-08-31 porque un inventario de faltantes dentro de un
documento de calificación no se lee como rigor sino como producto incompleto. Omitirla no
publica nada falso: el score ya excluye esos indicadores y renormaliza los pesos, y la
afirmación de MÉTODO vive una sola vez, en Limitaciones.

Lo que este test protege es lo de siempre y no cambió: el 0.0 por defecto NUNCA sale
publicado, ni con su valor ni con el 100 que la curva le da al cero.

El test es de COMPORTAMIENTO —construye la tabla y mira las celdas— y no de texto. Un test
que buscara `available` en el fuente pasaría en verde con solo mencionarlo en un comentario.
"""

from modules.banking_score.reports import pdf_generator as pdf
# nada: los estilos vienen del generador


def _texto(celda):
    """Las celdas de la tabla de marca son `Paragraph`, no cadenas."""
    return celda if isinstance(celda, str) else celda.getPlainText()


def _celdas(indicadores, **kw):
    # Sin filas publicables no hay tabla: `_build_indicators_table` no la emite. Devolver {}
    # y no reventar es parte de lo que se comprueba.
    tabla = next((e for e in pdf._build_indicators_table(indicadores, pdf._get_styles(), **kw)
                  if hasattr(e, "_cellvalues")), None)
    if tabla is None:
        return {}
    filas = [[_texto(c) for c in fila] for fila in tabla._cellvalues[1:]]
    return {fila[0]: fila[1:] for fila in filas}


_SIN_DATO = {"raw": 0.0, "score": 100.0, "available": False}
_CON_DATO = {"raw": 3.56, "score": 64.4, "available": True}


def test_el_indicador_no_disponible_no_muestra_ni_valor_ni_score():
    c = _celdas({"concentracion_top10": _SIN_DATO, "hhi_sectorial": _SIN_DATO,
                 "morosidad": _CON_DATO})
    for rotulo, celdas in c.items():
        if "orosidad" in rotulo:
            continue
        assert "0.00" not in celdas[0] and "0" != celdas[0].strip("% "), (
            f"«{rotulo}» publica el 0.0 por defecto como si fuera una medición: {celdas}")
        assert "100" not in celdas[1], (
            f"«{rotulo}» publica como PERFECTO un indicador sin dato: {celdas}. Para los "
            "inversos —concentración, HHI— el cero por defecto puntúa 100")


def test_la_fila_NO_se_publica():
    """El documento no inventaría lo que le falta (decisión del dueño, 2026-08-31)."""
    c = _celdas({"concentracion_top10": _SIN_DATO, "morosidad": _CON_DATO})
    assert len(c) == 1, f"el indicador sin dato sigue apareciendo en la tabla: {c}"
    assert "orosidad" in next(iter(c))


def test_el_indicador_CON_dato_sigue_publicando_su_valor():
    """El contra-caso: sin esto, romper la tabla entera pasaría el test de arriba."""
    c = _celdas({"morosidad": _CON_DATO})
    rotulo = next(iter(c))
    assert "3.56" in c[rotulo][0] and "64.4" in c[rotulo][1], c


def test_tampoco_publica_percentil_ni_tendencia_de_lo_que_no_midio():
    """Las columnas de amplitud describirían el cero por defecto, no a la entidad. Al no
    emitirse la fila, no hay dónde publicarlas — pero se comprueba, porque el percentil y la
    tendencia entran por otra vía que la fila y podrían sobrevivir a su omisión."""
    c = _celdas({"concentracion_top10": _SIN_DATO},
                percentiles={"indicators": {"concentracion_top10":
                                            {"sector": {"percentile": 97.0}}}},
                trajectories={"indicators": {"concentracion_top10": {"delta": 38.0}}})
    assert c == {}, f"publica un indicador sin dato con su amplitud: {c}"


def test_la_afirmacion_de_METODO_sobrevive_en_Limitaciones():
    """Se sacó el inventario de faltantes, no la explicación del método. Si esta frase
    desapareciera, el documento dejaría de decir en ninguna parte que los pesos se
    renormalizan sobre lo medido — y ahí sí perderíamos algo que un lector profesional
    espera encontrar."""
    from modules.banking_score.products import _LIMITATIONS_TEXT
    assert "se renormalizan sobre lo efectivamente medido" in _LIMITATIONS_TEXT
    assert "no acredita ni penaliza un dato ausente" in _LIMITATIONS_TEXT


def test_el_documento_NO_inventaria_lo_que_le_falta():
    """El contra-test de la decisión: si alguien repone el marcado «s/d», esto lo frena."""
    c = _celdas({"concentracion_top10": _SIN_DATO, "morosidad": _CON_DATO})
    assert not any("s/d" in celda for celdas in c.values() for celda in celdas), c
