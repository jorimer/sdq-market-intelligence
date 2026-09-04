"""Una serie tiene UN dueño de su escala. Dos correcciones para el mismo hecho se componen.

Salió de una bomba de tiempo real. El archivo del BCRD guarda la TPM como fracción
(`0.0525`), y había DOS lugares corrigiéndolo:

* `canonical.ESCALAS_CURADAS`, que multiplica ×100 **en la ingesta** y trae un tope que la
  hace idempotente — si el BCRD republica en por-ciento, no vuelve a multiplicar;
* `shared/doctrine/macro_sector.yaml`, con `scale: 100.0` **en la lectura** y sin tope.

Mientras producción sirvió los valores viejos las dos convivieron sin chocar. En cuanto la
sincronización canónica corriera con la corrección de la ingesta, la segunda se aplicaría
ENCIMA y el factor de política monetaria se habría publicado como **«525 %»** — una cifra
absurda, en el contrato macro que `banking_score` consume para su Entorno Operativo.

No falló ningún test porque cada mitad, por su lado, estaba bien.
"""
import ast
import pathlib

from shared.data.bcrd_excel import canonical
from shared.doctrine import load_doctrine_raw

def _factores():
    """Por el cargador del repo, no leyendo el YAML a mano: una segunda forma de leer la
    doctrina es una segunda doctrina."""
    return load_doctrine_raw("macro_sector").get("factors") or []


def test_ningun_factor_declara_scale_para_una_serie_con_escala_curada():
    """El guard estructural: si las dos existen para la misma serie, se componen."""
    choques = []
    for f in _factores():
        code = f.get("series_code") or ""
        if not f.get("scale"):
            continue
        if any(code.startswith(p) for p in canonical.ESCALAS_CURADAS):
            choques.append((f.get("key"), code, f.get("scale")))
    assert not choques, (
        "estos factores declaran `scale` en la doctrina para una serie que YA tiene escala "
        f"curada en el registro canónico; las dos se aplican en cadena: {choques}")


def test_la_escala_curada_de_la_tpm_sigue_existiendo():
    """El otro lado del guard: si alguien borra la escala curada creyendo que la doctrina la
    cubre, la TPM pasa a publicarse como 0,0525."""
    assert any(p.startswith("bcrd.xls.serie_tpm") for p in canonical.ESCALAS_CURADAS)


def test_la_escala_curada_es_idempotente():
    """El tope es lo que distingue una corrección de una multiplicación ciega."""
    code = "bcrd.xls.serie_tpm.tasa_de_politica_monetaria"
    assert canonical.escala_curada(code, 0.0525) == 5.25
    assert canonical.escala_curada(code, 5.25) == 5.25


def test_el_lector_de_factores_no_encadena_las_dos_correcciones():
    """Lee el código: la rama del `scale` de la doctrina es EXCLUYENTE de la curada."""
    fuente = pathlib.Path("modules/macro_monitor/macro_context.py").read_text()
    arbol = ast.parse(fuente)
    usa_curada = any(
        isinstance(n, ast.Attribute) and n.attr == "escala_curada"
        for n in ast.walk(arbol))
    assert usa_curada, "macro_context ya no consulta la escala curada del registro canónico"
    # El `scale` de la doctrina tiene que vivir dentro de un `else`, no en línea recta.
    en_rama = False
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.If):
            continue
        for hijo in ast.walk(nodo):
            if (isinstance(hijo, ast.Constant) and hijo.value == "scale"):
                en_rama = True
    assert en_rama, (
        "el `scale` de la doctrina se aplica sin condicionarlo a la escala curada: las dos "
        "correcciones se componen y la TPM se publica multiplicada dos veces")
