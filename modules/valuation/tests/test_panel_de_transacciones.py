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


def test_el_gate_ABIERTO_igual_dice_que_NO_valida_el_modelo():
    """Un `abierto=True` con motivo vacío se leería como «ya está validado».

    Es el riesgo del momento en que un gate cruza su umbral: lo que abre es la vista de
    fusiones y adquisiciones, no una afirmación de que el modelo predice precios.
    """
    e = tx.estado()
    assert e.abierto and e.n_comparables >= e.minimo
    assert e.motivo, "el gate abrió con motivo vacío"
    assert "NO contrasta el modelo" in e.motivo


def test_el_minimo_son_OCHO_casos():
    assert tx.MINIMO_DE_CASOS == 8


def test_hay_ONCE_verificables_y_OCHO_COMPARABLES():
    """La distinción que decide si la vista de M&A se abre.

    Las once tienen las dos puntas publicadas. Solo ocho están sobre patrimonio CONTABLE,
    que es la base contra la que valúa el Excess Return. Las otras dos vienen de la NIIF 3,
    cuyo denominador son activos netos a VALOR RAZONABLE — lo que el COMPRADOR reconoce, no
    lo que el vendedor tenía en libros.
    """
    assert len([t for t in tx.PANEL if t.verificable]) == 11
    comparables = [t for t in tx.PANEL if t.comparable]
    assert len(comparables) == 8
    assert {t.pais for t in comparables} == {"DO", "PR", "KY", "TT", "BB"}
    progreso = next(t for t in comparables if "Progreso" in t.adquirida)
    assert progreso.pb == pytest.approx(2.531, abs=0.001)


def test_el_gate_cuenta_COMPARABLES_y_no_verificables():
    """Contar los once habría abierto la vista con una tabla que mezcla dos bases —y ahora
    que el gate CRUZÓ su umbral, contarlos mal la habría abierto tres casos antes.

    La exclusión se comprueba sobre los datos y no sobre la prosa del motivo: el texto cambia
    según el gate esté abierto o cerrado, y un test atado a él se rompe por la razón
    equivocada o, peor, pasa por la razón equivocada.
    """
    e = tx.estado()
    assert e.n_verificables == 11 and e.n_comparables == 8
    excluidos = [t for t in tx.PANEL if t.verificable and not t.comparable]
    assert len(excluidos) == e.n_verificables - e.n_comparables == 3
    assert all(t.base == tx.BASE_VALOR_RAZONABLE for t in excluidos)


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
    assert t.tipo_de_cambio == 54.9967, "el tipo de cambio no es el de junio 2022"


def test_las_VIAS_ABIERTAS_nombran_QUE_falta_en_cada_una():
    """Un relevamiento accionable no dice «no se pudo»: dice qué falta exactamente. La de
    Banco Río es el caso: el denominador YA está —la SB lo publica bajo el nombre posterior
    de la entidad—, y lo que bloquea es la fecha."""
    assert len(tx.VIAS_ABIERTAS) >= 3
    for nombre, falta in tx.VIAS_ABIERTAS:
        assert nombre and len(falta) > 60, f"«{nombre}» sin decir qué falta"
    assert not any("Río" in n for n, _f in tx.VIAS_ABIERTAS), (
        "Banco Río sigue listado como vía y ya es un caso cerrado del panel")
    clarien = next(f for n, f in tx.VIAS_ABIERTAS if "Clarien" in n)
    assert "SUSCRIBIÓ" in clarien, (
        "no dice que lo que falta es saber QUÉ FUE la operación: una suscripción es un "
        "aporte de capital, no un precio pagado a un vendedor")


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
    assert len(niif) == 3
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


def test_TODO_multiplo_del_panel_se_recomputa_desde_sus_INSUMOS():
    """El invariante que cubre a todo el panel de una vez.

    Las dos correcciones que hace `denominador_homogeneo` —la moneda al tipo de cambio del
    corte y la FRACCIÓN que compró el precio— ya entraron mal en este relevamiento: una
    conversión de prensa hecha a un mes que no era el del corte, y un precio por el 90 %
    contra un patrimonio del 100 %. Ninguna de las dos se ve mirando el múltiplo, porque el
    número sale plausible. Por eso se cruza contra los insumos y no se revisa a ojo.
    """
    for t in tx.PANEL:
        assert t.pb_recomputado is not None, f"{t.adquirida}: el múltiplo no es reproducible"
        assert t.pb == pytest.approx(t.pb_recomputado, abs=0.001), (
            f"{t.adquirida}: pb={t.pb} pero sus insumos dan {t.pb_recomputado:.4f}")


def test_una_compra_PARCIAL_homogeneiza_el_denominador():
    """Banco Río es el 90 %. Contra el patrimonio entero el múltiplo daría 1,47x en vez de
    1,64x —un 10 % bajo— y saldría plausible, que es lo que lo hace peligroso."""
    t = next(x for x in tx.PANEL if "Río" in x.adquirida)
    assert t.porcentaje == 0.90
    sin_homogeneizar = t.precio / (t.valor_libro / t.tipo_de_cambio)
    assert t.pb == pytest.approx(1.636, abs=0.001)
    assert sin_homogeneizar == pytest.approx(1.473, abs=0.001)
    assert t.pb > sin_homogeneizar


def test_el_100_por_ciento_es_el_DEFECTO_y_no_hay_que_declararlo():
    """Un campo que hubiera que acordarse de poner se olvidaría, y el olvido inflaría el
    denominador en silencio. El defecto es el caso seguro."""
    assert tx.Transaccion(
        anio=2020, comprador="C", adquirida="A", pais="DO", precio=2.0, moneda_precio="USD",
        valor_libro=1.0, moneda_libro="USD", periodo_libro="2020-01", pb=2.0,
        fuente_precio="x", fuente_libro="y").porcentaje == 1.0


def test_sin_tipo_de_cambio_el_denominador_NO_se_convierte():
    """Los casos en una sola moneda —OFG— no llevan conversión, y el que no la lleva no
    puede recibir una por defecto: un 1,0 implícito pasaría inadvertido en un caso en
    pesos."""
    ofg = next(x for x in tx.PANEL if "OFG" in x.comprador)
    assert ofg.tipo_de_cambio is None
    assert ofg.denominador_homogeneo == ofg.valor_libro


def test_la_serie_MENSUAL_es_la_que_corrobora_la_fecha_de_Banco_Rio():
    """La evidencia que ninguna de las dos fuentes de prensa aportaba: el patrimonio cae sin
    interrupción hasta noviembre de 2015 y salta en diciembre. La capitalización llega
    después de julio de 2015, así que la operación no pudo ser de julio de 2014."""
    t = next(x for x in tx.PANEL if "Río" in x.adquirida)
    assert "1 de julio de 2015" in t.fuente_precio
    assert "CORROBORA LA FECHA" in t.fuente_libro
    assert "1,25x" in " ".join(t.caveats), "no declara lo que costaba equivocarse de fecha"


def test_la_CUNA_entre_bases_va_en_LAS_DOS_DIRECCIONES():
    """El hallazgo que sostiene toda la regla del panel, y que ya no es un argumento.

    La misma compradora —OFG—, en el mismo mercado, publicó las dos columnas dos veces con
    siete años de diferencia. En BBVA (2012) el valor razonable queda MUY POR DEBAJO del
    libro: se marcó la cartera y desapareció el goodwill heredado. En Scotiabank (2019) queda
    POR ENCIMA: se reconoció un intangible de depósitos que el vendedor no tenía.

    Mientras las dos cuñas tuvieran el mismo signo, alguien podía proponer un ajuste fijo que
    convirtiera una base en la otra. Con signos opuestos y casi cincuenta puntos de amplitud,
    ese ajuste no existe — y por eso las dos bases no van en la misma tabla.
    """
    con_las_dos = [t for t in tx.PANEL if t.valor_razonable is not None]
    assert len(con_las_dos) >= 2
    cunas = [t.cuna_de_base_pct for t in con_las_dos]
    assert min(cunas) < 0 < max(cunas), (
        "todas las cuñas tienen el mismo signo: con una sola dirección, un ajuste fijo entre "
        "bases sería defendible y la regla del panel perdería su fundamento")
    assert max(cunas) - min(cunas) > 40, f"amplitud de solo {max(cunas)-min(cunas):.1f} pp"
    assert len({t.comprador for t in con_las_dos}) == 1, (
        "las dos mediciones ya no son del mismo comprador: el argumento es más fuerte "
        "cuando el criterio contable es el mismo y aun así el signo cambia")


def test_BBVA_es_una_compra_POR_DEBAJO_del_libro():
    """El panel no puede ser solo de primas. Un múltiplo por debajo de 1,0x existe y este es
    el caso: si todos los observados estuvieran por encima, el panel estaría sesgado por
    selección y el modelo se validaría contra una muestra que solo mira hacia arriba."""
    t = next(x for x in tx.PANEL if "BBVA" in x.adquirida)
    assert t.pb < 1.0 and t.base == tx.BASE_CONTABLE
    assert min(x.pb for x in tx.PANEL if x.comparable) < 1.0


def test_CAYMAN_toma_el_denominador_de_la_ADQUIRIDA_y_no_del_comprador():
    """La estructura ideal de un caso: la adquirida cotizaba y publicaba sus estados
    auditados, así que el denominador no depende de lo que el comprador decida contar."""
    t = next(x for x in tx.PANEL if "Cayman" in x.adquirida)
    assert t.moneda_libro == "KYD" and t.porcentaje == 0.7499
    assert "AUDITADOS de Cayman National" in t.fuente_libro
    assert "peg FIJO" in t.fuente_libro, "no declara que la conversión es una paridad fija"


def test_SANTANDER_no_cruza_el_ALCANCE_del_precio_con_el_del_regulador():
    """El error que produce un número plausible: el Call Report cubre el BANCO y el precio
    compró la TENEDORA. Cruzarlos daría 1,26x y parecería un P/B."""
    t = next(x for x in tx.PANEL if "Santander" in x.adquirida)
    assert t.base == tx.BASE_VALOR_RAZONABLE, (
        "el caso quedó sobre base contable usando el patrimonio del banco contra el precio "
        "de la tenedora")
    assert "error de ALCANCE" in " ".join(t.caveats)


def test_ABRIR_el_panel_no_es_VALIDAR_el_modelo():
    """La distinción más cara del eje, y la que se vuelve peligrosa justo ahora.

    El gate pidió ocho múltiplos comparables y los hay. Eso dice a cuánto sobre libro se paga
    un banco del Caribe — evidencia de MERCADO. No dice que este modelo acierte: para eso
    habría que valuar cada adquirida con el Excess Return a la fecha de su operación, y eso
    exige su historia de ROE y patrimonio, que solo tenemos donde ingerimos el balance por
    entidad.

    Dejar que el gate abierto arrastre la segunda afirmación sería cierto en la forma y falso
    en el fondo, que es el modo de falla que esta plataforma existe para no tener.
    """
    e, c = tx.estado(), tx.contraste_del_modelo()
    assert e.abierto, "el panel ya no llega a ocho; este test perdió su sentido"
    assert not c.contrasta_el_modelo
    assert c.n_valuables < c.n_comparables
    assert "NO contrasta el modelo" in c.motivo


def test_el_contraste_cuenta_las_adquiridas_que_PODRIAMOS_valuar():
    """Se computa desde el panel y la cobertura de balances, no se escribe a mano."""
    c = tx.contraste_del_modelo()
    esperado = len([t for t in tx.PANEL if t.comparable and t.pais in tx.PAISES_CON_MOTOR])
    assert c.n_valuables == esperado
    assert tx.PAISES_CON_MOTOR == ("DO",), (
        "cambió la cobertura de balances por entidad: revisar si el contraste ya es posible")


def test_si_TODAS_fueran_dominicanas_el_contraste_seguiria_declarandose_por_dato():
    """Contraejemplo: sin esto, un `contrasta_el_modelo=False` constante pasaría el test de
    arriba sin medir nada. Con las ocho valuables, el conteo tiene que reflejarlo."""
    todas_do = tuple(
        tx.Transaccion(anio=2020 + i, comprador="C", adquirida=f"A{i}", pais="DO",
                       precio=2.0, moneda_precio="USD", valor_libro=1.0, moneda_libro="USD",
                       periodo_libro="2020-01", pb=2.0, fuente_precio="x", fuente_libro="y")
        for i in range(tx.MINIMO_DE_CASOS))
    c = tx.contraste_del_modelo(todas_do)
    assert c.n_valuables == c.n_comparables == tx.MINIMO_DE_CASOS


def test_el_resumen_del_panel_se_COMPUTA():
    """Rango y mediana salen de los comparables, no de un texto. Y solo de los comparables:
    meter un múltiplo sobre valor razonable movería la mediana sin que se note."""
    r = tx.resumen()
    pbs = sorted(t.pb for t in tx.PANEL if t.comparable)
    assert r.n == len(pbs) == 8
    assert r.minimo == pbs[0] and r.maximo == pbs[-1]
    assert r.mediana == pytest.approx((pbs[3] + pbs[4]) / 2)
    assert r.minimo < 1.0 < r.maximo, "el panel dejó de tener casos a los dos lados del libro"


def test_toda_transaccion_declara_su_ALCANCE():
    """El perímetro que cubren las DOS puntas. Es la condición para que el caso exista: un
    precio de la tenedora contra un patrimonio del banco da un múltiplo plausible y
    equivocado."""
    for t in tx.PANEL:
        assert t.alcance and len(t.alcance) >= 7, f"{t.adquirida} sin alcance declarado"
    butterfield = next(t for t in tx.PANEL if "Butterfield" in t.adquirida)
    assert "CONSOLIDADAS" in butterfield.alcance, (
        "no declara que el denominador es la medición del grupo vendedor y no el patrimonio "
        "individual de la entidad")


def test_RBTT_reconcilia_sus_DOS_formas_de_precio():
    """El precio existe por acción (TT$40) y agregado (US$2.200 M). Que concuerden a un tipo
    de cambio real de 2008 es lo que permite usar el total sin elegir una cotización."""
    t = next(x for x in tx.PANEL if "RBTT" in x.adquirida)
    implicito = t.precio / 2_200_000_000.0
    assert 6.20 < implicito < 6.35, f"TT$/US$ implícito {implicito:.4f} fuera del rango real"
    assert "más vieja del panel" in " ".join(t.caveats).lower() or "2008" in " ".join(t.caveats)
