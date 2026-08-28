

def test_la_huella_de_la_receta_incluye_las_PLANTILLAS_por_seccion():
    """Cambiar el prompt de una sección tiene que invalidar la caché de reportes.

    No lo hacía: la huella derivaba de la doctrina compartida (`cerebro`) y dejaba fuera
    `THIN_TEMPLATES`, que es donde se arregla la redacción de cada sección. Verificado en
    producción — se corrigió `early_warning_reading` para que ubicara bien el horizonte,
    se desplegó, y el informe siguió sirviendo «el margen desaparecería alrededor de 3.5 años
    antes de que las reservas dejen de cubrir». `ProductReportCache` vive en Postgres y NO
    tiene TTL: sin esto, la frase rota se sirve indefinidamente.
    """
    from shared.narrative import claude_engine as ce
    from shared.products.assembler import _narrative_logic_version

    antes = _narrative_logic_version()
    original = ce.THIN_TEMPLATES["early_warning_reading"]
    try:
        ce.THIN_TEMPLATES["early_warning_reading"] = original + "\nUNA REGLA NUEVA."
        assert _narrative_logic_version() != antes, (
            "tocar una plantilla no movió la huella: el arreglo existiría en el código y "
            "nunca en el informe")
    finally:
        ce.THIN_TEMPLATES["early_warning_reading"] = original
    assert _narrative_logic_version() == antes, "la huella debe ser estable con la receta fija"


def test_una_seccion_que_el_producto_PRODUJO_entra_al_orden():
    """El orden es lo que la app dibuja: fuera de él, la sección no existe para el cliente.

    **El caso, del 2026-08-27.** El año por trimestres se sirve como una sección que el
    manifiesto NO declara —depende del PERÍODO pedido, no del nivel—. Quedaba en
    `narratives` pero fuera del orden, y el orden es exactamente lo que viaja a la app como
    `commercial.sections`.

    En pantalla: «1. Metodología y fuentes», «2. Fuentes y referencias», y NADA en medio. El
    PDF salía completo porque su render recibe la lista por otra vía. Sin error, sin aviso, y
    con la superficie que el cliente mira primero siendo la que falló.
    """
    from shared.products.assembler import orden_de_secciones

    orden = orden_de_secciones(
        ("resumen",),
        {"resumen": "a", "anio_por_trimestres": "b", "metodologia": "c", "glosario": "d"},
        {"metodologia": "c", "glosario": "d"})
    assert "anio_por_trimestres" in orden, (
        "la sección tiene texto y no entra al orden: la app no la va a dibujar")


def test_las_estandar_CIERRAN_el_documento():
    """Metodología y fuentes van al final. Si el bloque nuevo se anexara después, el informe
    terminaría con su contenido después de las fuentes."""
    from shared.products.assembler import orden_de_secciones

    orden = list(orden_de_secciones(
        ("resumen",), {"resumen": "a", "propia": "b", "metodologia": "c"},
        {"metodologia": "c"}))
    assert orden.index("propia") < orden.index("metodologia")
    assert orden[0] == "resumen"


def test_sin_secciones_propias_el_orden_no_cambia():
    """El contrapeso: la inmensa mayoría de los informes no producen secciones de más, y su
    orden tiene que quedar idéntico."""
    from shared.products.assembler import orden_de_secciones

    assert orden_de_secciones(
        ("a", "b"), {"a": "1", "b": "2", "glosario": "g"}, {"glosario": "g"}
    ) == ("a", "b", "glosario")


def test_una_seccion_declarada_SIN_texto_conserva_su_lugar():
    """Se ordena por lo DECLARADO, no por lo que haya en el dict: una sección que el nivel
    lista y que vino vacía no puede desaparecer del orden en silencio."""
    from shared.products.assembler import orden_de_secciones

    assert "b" in orden_de_secciones(("a", "b"), {"a": "1"}, {})
