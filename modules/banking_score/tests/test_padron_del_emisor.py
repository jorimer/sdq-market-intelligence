"""Los DOS padrones del emisor tienen que decir lo mismo.

**El defecto, medido el 2026-09-01.** La Superintendencia dejó de emitir «FONDESA» y «BACC»
y pasó a «BANFONDESA» y «BANCO BACC». El emparejador del cliente no reconoció las formas
nuevas y las dos entidades quedaron CONGELADAS en 2026-03-31 —21 períodos contra los 22 de
sus trece pares, sin el trimestre de junio y sin desglose sectorial— mientras el resto del
padrón seguía al día. La deriva es acumulativa: cada trimestre que pasa las deja un corte
más atrás.

**Y las formas nuevas YA ESTABAN escritas en el repo**, en el mapa curado
`SIMBAD_TO_PROD` de `scripts/qa_simbad_per_entity.py`. Alguien las reconcilió contra la
fuente y lo dejó en un script de QA en vez de en el cliente: dos copias del mismo padrón,
una actualizada y la otra no. Es el mismo patrón que rompió el conector del SISDOM el mismo
día, por la misma causa.

Este test cruza las dos copias. Habría atrapado esto solo, y atrapa el próximo rename.

Se lee el script con `ast` en vez de importarlo: es un ejecutable con efectos, y `ast` no
corre nada. (La otra razón está en la doctrina del repo: un lector de código se escribe con
`ast`, no con regex.)
"""
import ast
from pathlib import Path

import pytest

from modules.banking_score.external.sib_data_client import SIB_ENTITY_CODES, SIBDataClient
from modules.banking_score.sib_sync import _SHORT_TO_NAME

_QA = Path(__file__).resolve().parents[3] / "scripts" / "qa_simbad_per_entity.py"

#: Nombres que el emisor emite y que NO tenemos catalogados. Se declaran con su motivo —no
#: se borran del mapa curado— porque la ausencia es el dato: son entidades supervisadas que
#: la plataforma todavía no cubre. Hoy está vacío; el `sync-status` de producción lista
#: aparte a BANCAMERICA y BELLBANK, que no están en `SIMBAD_TO_PROD`.
SIN_CATALOGAR: dict = {}

#: Nombres cortos que el CLIENTE cataloga y que la siembra no trae. No es un defecto —son
#: entidades supervisadas sin fila propia en `banking_seed`— pero se enumeran para que la
#: lista no crezca en silencio: una entidad que caiga acá sin querer deja de tener nombre
#: propio en la plataforma.
SIN_SIEMBRA = frozenset({"Activo", "Atlántico", "Cofaci", "Empire", "Reidco", "Óptima"})


def _mapa_curado() -> dict:
    """`SIMBAD_TO_PROD` leído del fuente, sin ejecutar el script."""
    arbol = ast.parse(_QA.read_text(encoding="utf-8"))
    for nodo in arbol.body:
        if not isinstance(nodo, ast.Assign):
            continue
        for destino in nodo.targets:
            if isinstance(destino, ast.Name) and destino.id == "SIMBAD_TO_PROD":
                return ast.literal_eval(nodo.value)
    raise AssertionError(f"{_QA.name} ya no declara SIMBAD_TO_PROD: ¿se renombró o se movió?")


MAPA = _mapa_curado()


def test_el_mapa_curado_no_esta_vacio():
    """Un barrido que no encuentra nada pasa en verde sin proteger nada."""
    assert len(MAPA) >= 40, len(MAPA)


@pytest.mark.parametrize("emitido", sorted(MAPA))
def test_toda_forma_que_el_emisor_emite_empareja(emitido):
    short = SIBDataClient._match_entity_name(emitido)
    if emitido in SIN_CATALOGAR:
        assert short is None, (
            f"«{emitido}» está declarado SIN CATALOGAR pero ahora empareja: sacalo de "
            "SIN_CATALOGAR.")
        return
    assert short is not None, (
        f"el emisor emite «{emitido}» y el emparejador no lo reconoce. La entidad deja de "
        "recibir datos EN SILENCIO —sus períodos se congelan mientras los de sus pares "
        "avanzan—. Agregá el alias EXACTO en `SIB_API_NAME_MAP`, o declaralo en "
        "SIN_CATALOGAR con su motivo si es una entidad que no cubrimos.")


@pytest.mark.parametrize("emitido", sorted(MAPA))
def test_empareja_con_la_entidad_CORRECTA_y_no_con_otra(emitido):
    """No alcanza con que empareje: tiene que emparejar con la QUE ES.

    Un alias que resuelve a la entidad equivocada es peor que no resolver — rutea el balance
    de una a otra y nada falla. Es lo que pasó cuando el código «BON» ruteó el balance de
    Bonao a Bonanza.
    """
    if emitido in SIN_CATALOGAR:
        pytest.skip("declarada sin catalogar")
    short = SIBDataClient._match_entity_name(emitido)
    # El short devuelto tiene que EXISTIR. Sin esta línea, un alias que apunta a un nombre
    # corto inventado devolvía algo, `_SHORT_TO_NAME` no lo encontraba y el test se SALTABA
    # —en verde— contra el defecto que viene a buscar. Un skip no es una comprobación: es la
    # misma trampa que una aserción de ausencia que se satisface sola.
    assert short in SIB_ENTITY_CODES, (
        f"«{emitido}» resuelve a «{short}», que no es un nombre corto del catálogo del "
        "cliente. Un alias mal escrito manda los datos a la nada y nada falla.")
    nuestro = _SHORT_TO_NAME.get(short)
    if nuestro is None:
        # Entidades catalogadas en el cliente y sin fila de siembra. Se nombran para que la
        # lista no crezca en silencio: si aparece una nueva, este test lo dice.
        assert short in SIN_SIEMBRA, (
            f"«{short}» está en el cliente y no en la siembra, y no estaba declarado.")
        pytest.skip(f"«{short}» no tiene fila de siembra (declarado)")
    assert nuestro == MAPA[emitido], (
        f"el emisor emite «{emitido}» → el mapa curado dice «{MAPA[emitido]}» y el "
        f"emparejador devuelve «{nuestro}». Uno de los dos padrones está equivocado, y "
        "mientras no coincidan hay datos yendo a la entidad que no es.")


def test_las_formas_nuevas_del_emisor_resuelven():
    """La regresión concreta del 2026-09-01, escrita con nombre y apellido."""
    assert SIBDataClient._match_entity_name("BANFONDESA") == "FONDESA"
    assert SIBDataClient._match_entity_name("BANCO BACC") == "BACC"


def test_los_alias_nuevos_no_le_roban_a_nadie():
    """Las claves exactas no colisionan por diseño, pero los alias con espacio TAMBIÉN entran
    al respaldo por subcadena: se comprueba que los vecinos siguen resolviendo a lo suyo."""
    for emitido, esperado in (("BONAO", "Bonao"), ("BONANZA", "Bonanza"),
                              ("CARIBE", "Caribe"), ("FONDESA", "FONDESA"),
                              ("BACC", "BACC")):
        assert SIBDataClient._match_entity_name(emitido) == esperado, emitido
