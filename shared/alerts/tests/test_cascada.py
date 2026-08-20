"""La cascada: toda operación que produce dato despierta el barrido.

**Por qué la lista es de EXCLUSIÓN y no de inclusión.** Un barrido de más cuesta unas
consultas y no produce nada —todas las reglas son de transición, así que sin cambio no hay
evento—. Un barrido de menos cuesta que la alerta llegue un día tarde, que es justo lo que el
producto promete no hacer. Con una lista de inclusión, cada sync nuevo nacería mudo hasta que
alguien se acordara de agregarlo.

Los tests de abajo son el guard de esa decisión, y el primero es el que importa: si mañana
alguien registra `bcrd-nueva-fuente-sync`, queda enganchado solo y este test lo confirma.
"""
import pytest

from shared.alerts.motor import SIN_CASCADA, SWEEP_OP_NAME, enganchar_cascada


@pytest.fixture(autouse=True)
def app_arrancada():
    """El arranque real, con su orden real: la cascada se engancha después de que todos los
    módulos registraron sus operaciones."""
    import app.main  # noqa: F401


def _ops():
    from shared.operations.service import OPERATIONS

    return OPERATIONS


def test_toda_operacion_NO_excluida_despierta_el_barrido():
    """El guard central. Un sync nuevo nace enganchado; sacarlo hay que justificarlo."""
    faltantes = [n for n, op in _ops().items()
                 if n not in SIN_CASCADA and SWEEP_OP_NAME not in op.triggers]
    assert faltantes == [], (
        f"operaciones sin cascada al barrido y sin exclusión declarada: {sorted(faltantes)}")


def test_hay_operaciones_que_revisar():
    """Si el registro se vaciara, el test de arriba pasaría sin proteger nada — la misma
    forma de falla que un barrido con cero casos."""
    con_cascada = [n for n, op in _ops().items() if SWEEP_OP_NAME in op.triggers]
    assert len(con_cascada) > 50, (
        f"solo {len(con_cascada)} operaciones enganchadas: ¿corrió `enganchar_cascada()`?")


def test_el_barrido_NO_se_dispara_a_si_mismo():
    """Una cascada reflexiva es un bucle infinito de operaciones."""
    assert SWEEP_OP_NAME not in _ops()[SWEEP_OP_NAME].triggers


def test_el_digest_no_re_dispara_el_barrido():
    """Consume alertas, no produce dato: re-barrer después de mandar el resumen no puede
    encontrar nada nuevo y solo agrega ruido al historial de operaciones."""
    assert SWEEP_OP_NAME not in _ops()["alerts-digest"].triggers


def test_cada_EXCLUSION_corresponde_a_una_operacion_REAL():
    """Una exclusión con el nombre mal escrito no protege nada y encima esconde que la
    operación sí está cascadeando. Es el mismo defecto que un binding a algo inexistente:
    no falla, desaparece."""
    inexistentes = [n for n in SIN_CASCADA if n not in _ops()]
    assert inexistentes == [], (
        f"exclusiones que no corresponden a ninguna operación: {sorted(inexistentes)}")


def test_cada_exclusion_declara_su_MOTIVO():
    """Sacar una operación de la cascada es una decisión; sin el motivo escrito, el próximo
    que la lea no puede saber si sigue siendo válida."""
    assert all(motivo.strip() for motivo in SIN_CASCADA.values())


def test_engancharla_dos_veces_no_duplica():
    """El arranque puede reimportarse (tests, workers); un trigger duplicado dispararía dos
    veces la misma cascada."""
    enganchar_cascada()
    enganchar_cascada()
    assert _ops()["rescore"].triggers.count(SWEEP_OP_NAME) == 1


def test_la_cascada_PRESERVA_los_triggers_que_ya_existian():
    """`rescore` ya re-validaba (`backtest`). Pisar esa cascada por agregar la nuestra
    dejaría la validación sin recalcular, que es el defecto de los 19 días."""
    assert "backtest" in _ops()["rescore"].triggers
    assert "pension-backtest" in _ops()["sipen-sync"].triggers
    assert "esg-backtest" in _ops()["esg-sync"].triggers
