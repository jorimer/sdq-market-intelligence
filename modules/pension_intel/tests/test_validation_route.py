"""La ruta de validación de pensiones existe y no se la come el comodín de slug.

El motor del ISA corría, estaba testeado y su señal de rentabilidad era concluyente —Gini
0,1594 sobre 1.590 observaciones y 665 eventos, el N más grande del catálogo después de
banca— y **no había forma de leerla**: producción no tenía ninguna ruta de validación de
pensiones, así que `GET /api/v1/pension-intel/validation` devolvía el HTML del SPA con 200.
Un 200 con HTML es la forma más silenciosa de "esta ruta no existe".

Dos cosas que se verifican acá, y la segunda es la que se rompe sola con el tiempo: que la
ruta esté registrada, y que esté ANTES de `/{slug}/detail` — si algún día alguien la mueve
debajo, «validation» entraría por el comodín como si fuera el slug de una AFP y el endpoint
respondería 404 sobre una entidad inexistente.
"""


def _rutas():
    from modules.pension_intel.api.router import router

    return [(r.path, sorted(r.methods)) for r in router.routes]


def test_la_ruta_de_validacion_esta_registrada():
    rutas = dict((p, m) for p, m in _rutas())
    assert "/validation" in rutas, (
        "Sin esta ruta, el backtest del ISA corre y su resultado no es legible por API.")
    assert "GET" in rutas["/validation"]


def test_validation_se_resuelve_antes_que_el_comodin_de_slug():
    orden = [p for p, _m in _rutas()]
    assert orden.index("/validation") < orden.index("/{slug}/detail"), (
        "FastAPI resuelve por orden de registro: con `/{slug}/detail` antes, «validation» "
        "entraría como el slug de una AFP.")


def test_el_reporte_ausente_se_declara_en_vez_de_inventarse():
    """Sin reporte persistido, `backtest: None` — no un objeto vacío que parezca un cero."""
    from modules.pension_intel.api.router import validation
    import asyncio

    class _DB:
        def query(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def first(self):
            return None

    salida = asyncio.run(validation(db=_DB(), current_user=None))
    assert salida == {"backtest": None}
