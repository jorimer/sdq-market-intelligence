"""El panel de transacciones y su gate — y por qué está casi vacío.

**El relevamiento se hizo y midió algo.** Nueve fusiones y adquisiciones documentadas en la
banca dominicana desde 1996, y **una sola divulga precio**. En el Caribe, la operación mejor
documentada —Republic Financial por siete filiales de Scotiabank— publica el precio y la
PRIMA sobre el valor neto, pero **no el valor neto**.

O sea que el panel no está corto por falta de trabajo: está corto porque **el mercado divulga
el numerador y no el denominador**, y un múltiplo necesita las dos puntas.

**La que sí cierra, cierra porque el denominador es NUESTRO.** El patrimonio del Progreso está
en el histórico de la Superintendencia que esta plataforma ingiere, así que no depende de que
el comprador lo publique. Y coincide al peso con los activos que el artículo de prensa
reporta para el mismo mes — dos fuentes independientes sobre el mismo balance.
"""
import pytest

from modules.valuation.panel import transacciones as tx


def test_el_gate_esta_CERRADO_y_dice_por_que():
    e = tx.estado()
    assert not e.abierto
    assert e.n_verificables < e.minimo
    assert "no es falta de relevamiento" in e.motivo.lower()
    assert "las dos puntas" in e.motivo


def test_el_minimo_son_OCHO_casos():
    assert tx.MINIMO_DE_CASOS == 8


def test_hay_TRES_verificables_pero_una_sola_COMPARABLE():
    """La distinción que decide si la vista de M&A se abre.

    Las tres tienen las dos puntas publicadas. Solo una está sobre patrimonio CONTABLE, que
    es la base contra la que valúa el Excess Return. Las otras dos vienen de la NIIF 3, cuyo
    denominador son activos netos a VALOR RAZONABLE — lo que el COMPRADOR reconoce, no lo que
    el vendedor tenía en libros.
    """
    assert len([t for t in tx.PANEL if t.verificable]) == 3
    comparables = [t for t in tx.PANEL if t.comparable]
    assert len(comparables) == 1
    assert comparables[0].adquirida == "Banco Dominicano del Progreso"
    assert comparables[0].pb == pytest.approx(2.531, abs=0.001)


def test_el_gate_cuenta_COMPARABLES_y_no_verificables():
    """Sumar los tres abriría antes una vista cuya tabla mezcla dos bases, que es peor que
    tenerla cerrada."""
    e = tx.estado()
    assert e.n_verificables == 3 and e.n_comparables == 1
    assert "valor razonable" in e.motivo.lower()


def _caso(i: int, base: str) -> tx.Transaccion:
    return tx.Transaccion(
        anio=2000 + i, comprador=f"C{i}", adquirida=f"A{i}", pais="DO",
        precio=2.0, moneda_precio="USD", valor_libro=1.0, moneda_libro="DOP",
        periodo_libro="2020-01", pb=2.0, fuente_precio="x", fuente_libro="y", base=base)


def test_OCHO_verificables_con_UNA_sola_comparable_NO_abren_el_gate():
    """El caso que de verdad distingue las dos formas de contar.

    Con el panel real —tres casos y un mínimo de ocho— el gate queda cerrado cuente lo que
    cuente, así que un test sobre el panel real es CIEGO al defecto. Hace falta llegar al
    umbral con las bases mezcladas: ocho verificables de las cuales una sola es comparable.
    """
    mezclado = [_caso(0, tx.BASE_CONTABLE)] + [
        _caso(i, tx.BASE_VALOR_RAZONABLE) for i in range(1, tx.MINIMO_DE_CASOS)]
    e = tx.estado(mezclado)
    assert e.n_verificables == tx.MINIMO_DE_CASOS
    assert e.n_comparables == 1
    assert not e.abierto, (
        "el gate abrió con ocho verificables de las cuales una sola está sobre patrimonio "
        "contable: la tabla mezclaría dos bases, que es peor que tenerla cerrada")


def test_OCHO_comparables_SI_abren_el_gate():
    """El contraejemplo: un gate que nunca abriera pasaría el test de arriba."""
    e = tx.estado([_caso(i, tx.BASE_CONTABLE) for i in range(tx.MINIMO_DE_CASOS)])
    assert e.abierto and e.n_comparables == tx.MINIMO_DE_CASOS


def test_las_de_NIIF_3_declaran_su_base_y_su_aritmetica_CIERRA():
    """La validación interna del dato: precio = activos netos + goodwill, exacto."""
    niif = [t for t in tx.PANEL if t.base == tx.BASE_VALOR_RAZONABLE]
    assert len(niif) == 2
    for t in niif:
        assert "valor razonable" in " ".join(t.caveats).lower()
        assert "cierra" in t.fuente_libro.lower() or "aritmética" in t.fuente_libro.lower()


def test_el_caso_con_intangible_declara_QUE_PORCENTAJE_del_denominador_es():
    """En el Caribe Oriental el intangible de depósitos es el 62 % del denominador, y no
    existía en el balance del vendedor. Sin decirlo, 1,83x se leería como un P/B."""
    t = next(x for x in tx.PANEL if "Caribe Oriental" in x.adquirida)
    unidos = " ".join(t.caveats)
    assert "62 %" in unidos
    assert "no existía en el balance del vendedor" in unidos
    assert "DERIVACIÓN, no un dato" in unidos, (
        "el múltiplo sobre libro aproximado se publica sin marcarlo como derivación")


def test_una_transaccion_sin_valor_libro_NO_es_verificable():
    """El invariante que mantiene honesto al panel: un precio sin libro no es un múltiplo.

    Es el caso de la operación caribeña más grande, que publica precio y prima pero no el
    valor neto.
    """
    sin_libro = tx.Transaccion(
        anio=2019, comprador="X", adquirida="Y", pais="TT",
        precio=123_000_000.0, moneda_precio="USD",
        valor_libro=None, moneda_libro="USD", periodo_libro=None, pb=None,
        fuente_precio="anuncio", fuente_libro="no divulgado")
    assert not sin_libro.verificable
    assert tx.estado([sin_libro]).n_verificables == 0


def test_cada_punta_declara_su_fuente_POR_SEPARADO():
    """Un múltiplo con el precio público y el libro inventado no es verificable, y una nota
    de procedencia única lo escondería."""
    t = tx.PANEL[0]
    assert len(t.fuente_precio) > 60 and len(t.fuente_libro) > 60
    assert t.fuente_precio != t.fuente_libro
    assert "Superintendencia" in t.fuente_libro
    assert "verificación cruzada" in t.fuente_libro.lower()


def test_los_caveats_viajan_CON_el_dato():
    """Lo que el caso no permite afirmar se declara al lado del número, no en un anexo."""
    t = tx.PANEL[0]
    assert len(t.caveats) >= 3
    unidos = " ".join(t.caveats).lower()
    assert "100 %" in unidos or "100%" in unidos, "no declara la duda sobre el % de acciones"
    assert "sensible al mes" in unidos, "no declara la sensibilidad del denominador"


def test_las_DESCARTADAS_se_listan_con_su_motivo():
    """Un panel chico sin explicación se lee como falta de trabajo. Esto es lo contrario:
    es el resultado del trabajo."""
    assert len(tx.DESCARTADAS) >= 6
    for nombre, motivo in tx.DESCARTADAS:
        assert nombre and len(motivo) > 30, f"«{nombre}» descartada sin motivo suficiente"
    unidos = " ".join(m for _n, m in tx.DESCARTADAS).lower()
    assert "sin monto" in unidos
    assert "no el valor neto" in unidos, "no está el caso caribeño y su motivo"


def test_activos_consolidados_NO_se_confunden_con_un_precio():
    """El error que un panel de múltiplos existe para no cometer."""
    motivo = next(m for n, m in tx.DESCARTADAS if "Banaci" in n)
    assert "no son un precio" in motivo


def test_abrir_el_gate_exige_OCHO_verificables():
    """Contraejemplo: sin esto, un gate que devolviera siempre `abierto=False` pasaría todo."""
    ocho = tuple(
        tx.Transaccion(anio=2000 + i, comprador=f"C{i}", adquirida=f"A{i}", pais="DO",
                       precio=1.0, moneda_precio="USD", valor_libro=1.0, moneda_libro="DOP",
                       periodo_libro="2020-01", pb=1.0, fuente_precio="x", fuente_libro="y")
        for i in range(tx.MINIMO_DE_CASOS))
    assert tx.estado(ocho).abierto
    assert not tx.estado(ocho[:-1]).abierto
