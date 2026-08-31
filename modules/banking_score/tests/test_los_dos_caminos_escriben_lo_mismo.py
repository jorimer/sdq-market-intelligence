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


def test_nadie_arma_celdas_a_mano_al_lado_del_serializador():
    """No alcanza con que los caminos escriban los mismos CAMPOS: tienen que darles la misma
    FORMA, y la forma la fija UNA función.

    `_compute_carteras_metrics` emite sus celdas por dos bocas: `on_quarter`, que consume el
    backfill, y su valor de retorno, que consumen el recompute y el `_por_sector` que viaja
    dentro de `_map_to_sdq_fields`. La primera pasaba por `_celdas_serializadas`; la segunda
    tenía una COPIA A MANO de esa función —el mismo redondeo— a la que le faltaba derivar
    `tasa_ponderada` y descartar el numerador crudo. Dos de los tres consumidores escribían
    la tasa en NULL y el tercero no.

    Qué costó: el 2026-08-31 un recompute de 2026-03 corrido como experimento de control
    borró la tasa de 38 de las 41 entidades del corte. El promedio ponderado del sistema
    quedó computado sobre las tres que sobrevivieron y electricidad pasó de 8,14% a 33,60%
    — no un dato ausente sino uno ABSURDO, que es peor porque se puede citar.

    El test que había comparaba los campos de `BankingData` y por eso no lo vio: la
    divergencia estaba una capa más abajo, en cómo se arma la celda. Y la primera versión de
    ESTE test buscaba el string `_celdas_serializadas` en el fuente, y pasaba en verde contra
    el código roto porque el comentario que explica el arreglo menciona el nombre. Por eso se
    lee con `ast`: un test que se satisface con su propia documentación no protege nada.
    """
    import ast
    import inspect

    from modules.banking_score.external import sib_data_client

    # `ast.walk` y no `.body`: es un MÉTODO de una clase, y un barrido que solo mira el
    # nivel superior del módulo no lo encuentra — la primera versión de este test no
    # encontraba nada y fallaba por ausencia, que es la manera afortunada de equivocarse.
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(sib_data_client)))
              if isinstance(n, ast.FunctionDef) and n.name == "_compute_carteras_metrics")

    asignaciones = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "por_sector" for t in n.targets)]
    assert asignaciones, "`_compute_carteras_metrics` dejó de emitir el desglose sectorial"

    for a in asignaciones:
        de_la_funcion_compartida = (
            isinstance(a.value, ast.Call) and isinstance(a.value.func, ast.Name)
            and a.value.func.id == "_celdas_serializadas")
        assert de_la_funcion_compartida, (
            "las celdas del retorno se arman a mano, al lado del serializador que usa "
            "`on_quarter`: si esa copia no deriva `tasa_ponderada`, el recompute escribe la "
            "tasa en NULL mientras el backfill la escribe bien, y el promedio ponderado del "
            "sistema queda computado sobre las entidades que no pasaron por acá")


def test_la_serializacion_DERIVA_la_tasa_y_no_persiste_el_crudo():
    """La función que los dos caminos comparten. Si dejara de derivar, los dos escribirían
    NULL a la vez y el test de arriba seguiría en verde."""
    from modules.banking_score.external.sib_data_client import _celdas_serializadas

    celdas = _celdas_serializadas({
        ("Y - CONSUMO", "AZUA"): {"sector": "Y - CONSUMO", "provincia": "AZUA",
                                  "deuda": 1_000_000.0, "tasa_por_deuda": 18_000_000.0,
                                  "deuda_con_tasa": 1_000_000.0},
    })
    assert celdas and celdas[0]["tasa_ponderada"] == 18.0
    assert "tasa_por_deuda" not in celdas[0], (
        "el numerador crudo no se persiste: su unidad no está confirmada y alguien lo usaría "
        "creyendo que la entiende")


def test_recompute_sigue_escribiendo_lo_que_SÍ_le_corresponde():
    """El arreglo quita dos campos, no desactiva la operación."""
    from modules.banking_score import sib_sync
    src = inspect.getsource(sib_sync.recompute_carteras_metrics)
    for campo in ("cartera_total", "suma_top10", "hhi_sectorial_raw"):
        assert campo in src, f"el recompute deberia seguir escribiendo {campo}"
