

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
