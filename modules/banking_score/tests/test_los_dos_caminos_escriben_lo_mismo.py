"""Los dos caminos que enriquecen `BankingData` desde el cubo escriben LOS MISMOS campos.

El defecto. Hay dos rutas que leen el cubo de créditos y actualizan la fila de la entidad:
el backfill (`extract_all_entities_bulk` → `run_backfill`) y el recómputo puntual
(`recompute_carteras_metrics`, expuesto en la consola como «recompute-carteras»).

El backfill DECLARA y respeta una regla: no toca `cartera_vencida_90d` ni
`cartera_categoria_a`, porque morosidad y % de cartera vigente usan los ratios
pre-computados de la SIB y pisarlos con cifras del cubo los distorsiona. El recompute sí los
escribía. Los dos caminos discrepaban, y nada lo señalaba.

Qué costó. El 2026-08-29 se corrieron 22 recomputes manuales para poblar el desglose
sectorial —el cableado del backfill estaba roto— y eso metió la distorsión en los 22
trimestres de 89 entidades. Vivió un día en producción. Se descubrió al comparar 1.681
puntos de score contra una línea base: 680 se habían movido, y el «cambio» del backfill
siguiente era en realidad la corrección.

Es el patrón que este repo tiene nombrado —un guard presente en un motor y ausente en el
otro— aplicado al lado del DATO. La lección escrita no lo evitó; el test que lee el código,
sí.
"""

import ast
import inspect
import pathlib

import pytest

#: Los campos que NINGÚN camino del cubo debe escribir sobre `BankingData`. La razón vive en
#: el comentario de `sib_data_client`: son ratios pre-computados por la SIB.
PROHIBIDOS = {"cartera_vencida_90d", "cartera_categoria_a"}

_FUENTES = {
    "backfill": pathlib.Path("modules/banking_score/external/sib_data_client.py"),
    "recompute": pathlib.Path("modules/banking_score/sib_sync.py"),
}


def _asignaciones_a_row(fuente: pathlib.Path) -> set:
    """Campos asignados como `row.<campo> = …` en el archivo."""
    arbol = ast.parse(fuente.read_text())
    out = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                        and t.value.id == "row"):
                    out.add(t.attr)
    return out


def _claves_mapeadas(fuente: pathlib.Path) -> set:
    """Campos asignados como `mapped["<campo>"] = …` — la forma del camino del backfill."""
    arbol = ast.parse(fuente.read_text())
    out = set()
    for n in ast.walk(arbol):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Subscript)
                and isinstance(n.targets[0].value, ast.Name)
                and n.targets[0].value.id == "mapped"
                and isinstance(n.targets[0].slice, ast.Constant)):
            out.add(n.targets[0].slice.value)
    return out


def test_el_barrido_encuentra_los_dos_caminos():
    """Una aserción de ausencia pasa sola: esto comprueba que hay dónde mirar."""
    assert _asignaciones_a_row(_FUENTES["recompute"]), "no se detectó ninguna escritura a row"
    assert _claves_mapeadas(_FUENTES["backfill"]), "no se detectó ningún campo mapeado"


@pytest.mark.parametrize("camino", sorted(_FUENTES))
def test_ningun_camino_pisa_los_ratios_precomputados_de_la_SIB(camino):
    fuente = _FUENTES[camino]
    escritos = _asignaciones_a_row(fuente) | _claves_mapeadas(fuente)
    invasores = sorted(escritos & PROHIBIDOS)
    assert not invasores, (
        f"«{camino}» escribe {invasores} desde el cubo. Morosidad y % de cartera vigente "
        f"usan los ratios PRE-COMPUTADOS de la SIB: pisarlos con cifras del cubo los "
        f"distorsiona. Pasó el 2026-08-29 y vivió un día en producción.")


def test_la_regla_esta_DECLARADA_en_el_codigo_y_no_solo_en_el_test():
    """Si el comentario que explica el porqué desaparece, el próximo que lea el código no
    tiene forma de saber que la omisión es deliberada — y la 'arregla'."""
    texto = _FUENTES["backfill"].read_text()
    assert "deliberately do NOT touch" in texto
    assert "cartera_vencida_90d" in texto


def test_recompute_sigue_escribiendo_lo_que_SÍ_le_corresponde():
    """El arreglo quita dos campos, no desactiva la operación."""
    from modules.banking_score import sib_sync
    src = inspect.getsource(sib_sync.recompute_carteras_metrics)
    for campo in ("cartera_total", "suma_top10", "hhi_sectorial_raw"):
        assert campo in src, f"el recompute deberia seguir escribiendo {campo}"
