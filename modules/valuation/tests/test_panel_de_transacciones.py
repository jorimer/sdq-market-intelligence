"""El panel de transacciones y su gate — y por qué sigue corto.

**El relevamiento se hizo y midió algo.** Nueve fusiones y adquisiciones documentadas en la
banca dominicana desde 1996, y **una sola divulgó precio en su momento**. El panel no está
corto por falta de trabajo: está corto porque **el mercado divulga el numerador y casi nunca
el denominador**, y un múltiplo necesita las dos puntas.

**Las que cierran, cierran porque el denominador es NUESTRO.** El patrimonio de un banco
dominicano está en el histórico de la Superintendencia que esta plataforma ingiere y en
SIMBAD, su Superset público, así que no depende de que el comprador lo publique. Pasó dos
veces: el Progreso coincide al peso con los activos que la prensa reporta para el mismo mes,
y Bellbank coincide con sus estados auditados con **44 pesos** de diferencia sobre 217
millones.

**Y la distinción que gobierna el gate ya no se argumenta: se mide.** La NIIF 3 devuelve un
denominador a VALOR RAZONABLE, no el libro del vendedor. Cuánto se separan las dos bases lo
publica la tabla del 10-Q de OFG Bancorp, que trae las dos columnas sobre el mismo balance:
el valor razonable está 15,0 % por encima del libro.
"""
import pytest

from modules.valuation.panel import transacciones as tx


def test_el_gate_esta_CERRADO_y_dice_por_que():
    e = tx.estado()
    assert not e.abierto
    assert e.n_comparables < e.minimo
    assert "no es falta de relevamiento" in e.motivo.lower()
    assert "las dos puntas" in e.motivo


def test_el_minimo_son_OCHO_casos():
    assert tx.MINIMO_DE_CASOS == 8


def test_hay_CINCO_verificables_y_solo_TRES_COMPARABLES():
    """La distinción que decide si la vista de M&A se abre.

    Las cinco tienen las dos puntas publicadas. Solo tres están sobre patrimonio CONTABLE,
    que es la base contra la que valúa el Excess Return. Las otras dos vienen de la NIIF 3,
    cuyo denominador son activos netos a VALOR RAZONABLE — lo que el COMPRADOR reconoce, no
    lo que el vendedor tenía en libros.
    """
    assert len([t for t in tx.PANEL if t.verificable]) == 5
    comparables = [t for t in tx.PANEL if t.comparable]
    assert len(comparables) == 3
    assert {t.pais for t in comparables} == {"DO", "PR"}
    progreso = next(t for t in comparables if "Progreso" in t.adquirida)
    assert progreso.pb == pytest.approx(2.531, abs=0.001)


def test_el_gate_cuenta_COMPARABLES_y_no_verificables():
    """Sumar los cinco abriría antes una vista cuya tabla mezcla dos bases, que es peor que
    tenerla cerrada."""
    e = tx.estado()
    assert e.n_verificables == 5 and e.n_comparables == 3
    assert "valor razonable" in e.motivo.lower()


def test_OFG_mide_la_cuna_entre_bases_y_NO_la_transcribe():
    """El caso más valioso del panel, y no por su múltiplo.

    Su tabla auditada publica los DOS denominadores sobre el mismo balance y a la misma
    fecha, así que la distancia entre bases —el argumento entero del que depende el gate—
    deja de argumentarse y se mide. Y se computa desde las dos cifras: una cuña escrita a
    mano se desincroniza del dato en cuanto alguien corrija un denominador.
    """
    t = next(x for x in tx.PANEL if "OFG" in x.comprador)
    assert t.base == tx.BASE_CONTABLE, "el múltiplo publicado es sobre LIBRO"
    assert t.valor_razonable is not None
    assert t.cuna_de_base_pct == pytest.approx(
        (t.valor_razonable / t.valor_libro - 1.0) * 100.0)
    assert t.cuna_de_base_pct == pytest.approx(15.0, abs=0.1)


def test_sin_segundo_denominador_no_hay_cuna_INVENTADA():
    """Los otros cuatro casos no publican las dos columnas. La cuña es `None`, no un 0,0 ni
    el 15 % del caso que sí la tiene: rellenarla haría ver como medido lo que no se midió."""
    for t in tx.PANEL:
        if t.valor_razonable is None:
            assert t.cuna_de_base_pct is None, f"{t.adquirida} inventa una cuña"


def test_OFG_cruza_1_0x_segun_la_BASE_y_lo_declara():
    """El mismo precio da 1,13x sobre libro y 0,98x sobre valor razonable. Cruzar el umbral
    de 1,0x —«pagó más o menos que el patrimonio»— depende enteramente de la base, que es la
    demostración más económica de por qué las dos no van en la misma tabla."""
    t = next(x for x in tx.PANEL if "OFG" in x.comprador)
    assert t.precio / t.valor_libro > 1.0
    assert t.precio / t.valor_razonable < 1.0
    assert "0,98x" in " ".join(t.caveats)


def test_BELLBANK_reconcilia_contra_los_estados_AUDITADOS():
    """El denominador es nuestro y se cruza contra una fuente independiente: los estados
    auditados de la propia adquirida. La verificación viaja en la procedencia del libro."""
    t = next(x for x in tx.PANEL if "Bellbank" in x.adquirida)
    assert t.pais == "DO" and t.base == tx.BASE_CONTABLE
    assert "SIMBAD" in t.fuente_libro
    assert "44 pesos" in t.fuente_libro, "no declara la magnitud de la discrepancia"
    assert t.periodo_libro == "2022-06", (
        "el corte tiene que ser el mes de la autorización: precio, patrimonio y tipo de "
        "cambio a la misma fecha")


def test_BELLBANK_usa_el_tipo_de_cambio_del_CORTE_y_no_el_de_la_prensa():
    """La prensa convirtió a un tipo implícito de RD$54,46 que no es el del mes del
    patrimonio (RD$57,16 en diciembre 2021). Tomar la conversión publicada habría dado 1,80x
    en vez de 1,89x, y el error habría entrado como si fuera dato."""
    t = next(x for x in tx.PANEL if "Bellbank" in x.adquirida)
    unidos = " ".join(t.caveats)
    assert "57,16" in unidos and "54,46" in unidos
    assert t.pb == pytest.approx(t.precio / (t.valor_libro / 54.9967), abs=0.002), (
        "el múltiplo publicado no sale del patrimonio del corte con el tipo de cambio de "
        "ese mismo mes")


def test_las_VIAS_ABIERTAS_nombran_QUE_falta_en_cada_una():
    """Un relevamiento accionable no dice «no se pudo»: dice qué falta exactamente. La de
    Banco Río es el caso: el denominador YA está —la SB lo publica bajo el nombre posterior
    de la entidad—, y lo que bloquea es la fecha."""
    assert len(tx.VIAS_ABIERTAS) >= 3
    for nombre, falta in tx.VIAS_ABIERTAS:
        assert nombre and len(falta) > 60, f"«{nombre}» sin decir qué falta"
    rio = next(f for n, f in tx.VIAS_ABIERTAS if "Río" in n)
    assert "LA FECHA, no el denominador" in rio
    assert "SIMBAD" in rio


def test_una_operacion_que_NO_se_consumo_no_es_una_transaccion():
    """Un precio anunciado que nunca se pagó no es un dato del panel: no hubo transferencia
    de control que observar."""
    motivo = next(m for n, m in tx.DESCARTADAS if "FirstCaribbean" in n)
    assert "NO SE CONSUMÓ" in motivo
    assert not any("FirstCaribbean" in t.adquirida for t in tx.PANEL)


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
    assert "falta el numerador" in unidos, (
        "no está el descarte INVERSO —Clarien, con denominador público y sin precio—, que es "
        "el que muestra que el relevamiento buscó las dos puntas y no solo una")


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
