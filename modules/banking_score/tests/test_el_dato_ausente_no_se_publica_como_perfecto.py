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

La fila se LISTA marcada y no se esconde: una fila ausente se lee como que el indicador no
existe para esta entidad, cuando lo que pasa es que no vino el dato en este corte.

El test es de COMPORTAMIENTO —construye la tabla y mira las celdas— y no de texto. Un test
que buscara `available` en el fuente pasaría en verde con solo mencionarlo en un comentario.
"""

from modules.banking_score.reports import pdf_generator as pdf
# nada: los estilos vienen del generador


def _texto(celda):
    """Las celdas de la tabla de marca son `Paragraph`, no cadenas."""
    return celda if isinstance(celda, str) else celda.getPlainText()


def _celdas(indicadores, **kw):
    tabla = next(e for e in pdf._build_indicators_table(indicadores, pdf._get_styles(), **kw)
                 if hasattr(e, "_cellvalues"))
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


def test_la_fila_SIGUE_estando_marcada_y_no_desaparece():
    """Esconderla se lee como que el indicador no existe para la entidad."""
    c = _celdas({"concentracion_top10": _SIN_DATO, "morosidad": _CON_DATO})
    assert len(c) == 2, f"la fila sin dato desapareció en vez de declararse: {c}"
    rotulo = next(r for r in c if "orosidad" not in r)
    assert c[rotulo][0] == "s/d"


def test_el_indicador_CON_dato_sigue_publicando_su_valor():
    """El contra-caso: sin esto, romper la tabla entera pasaría el test de arriba."""
    c = _celdas({"morosidad": _CON_DATO})
    rotulo = next(iter(c))
    assert "3.56" in c[rotulo][0] and "64.4" in c[rotulo][1], c


def test_tampoco_publica_percentil_ni_tendencia_de_lo_que_no_midio():
    """Las columnas de amplitud: un percentil o una tendencia de un indicador sin dato
    describen el cero por defecto, no a la entidad."""
    c = _celdas({"concentracion_top10": _SIN_DATO},
                percentiles={"indicators": {"concentracion_top10":
                                            {"sector": {"percentile": 97.0}}}},
                trajectories={"indicators": {"concentracion_top10": {"delta": 38.0}}})
    rotulo = next(iter(c))
    assert c[rotulo][2] == "—" and c[rotulo][3] == "—", (
        f"publica amplitud de un indicador sin dato: {c[rotulo]}")


def test_la_nota_al_pie_DICE_que_no_se_acredita_ni_se_penaliza():
    """El lector tiene que poder distinguir «no vino» de «midió cero»."""
    assert "no vino" in pdf._NOTA_SIN_DATO
    assert "renormalizan" in pdf._NOTA_SIN_DATO
