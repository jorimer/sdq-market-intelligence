"""ESTRUCTURAL: un rótulo que no entra en su columna tumba la sync ENTERA en producción.

Tres veces en este repo, y las tres con el mismo final: SQLite no valida el largo de un
`varchar`, así que los tests pasan en verde; Postgres sí, y devuelve
`StringDataRightTruncation` al comitear — que no pierde una fila, aborta la transacción y se
lleva puesta la corrida completa.

- `mm_series`, la primera vez.
- `FUENTE_CONTEO`, que medía 41 caracteres contra un `varchar(40)`.
- Las unidades del MEM, de 52 — **con el comentario sobre el largo escrito tres líneas más
  arriba**: la advertencia estaba puesta sobre `source` y el desborde ocurrió en `unit`.

Por eso la regla la comprueba el código y no una lección escrita: la lección ya estaba escrita.
Los largos se leen del MODELO, así que si alguien ensancha la columna el test lo sigue solo.
"""
import ast
import inspect

from modules.social_dev.models.models import SocialIndicator

#: Columnas cuyo contenido se escribe a mano en el módulo de sync. `theme` entra porque un
#: tema largo rompe igual, aunque hoy ninguno se acerque.
COLUMNAS = ("theme", "unit", "source")


def _largo(col: str) -> int:
    tipo = SocialIndicator.__table__.columns[col].type
    largo = getattr(tipo, "length", None)
    assert largo, f"la columna {col} no declara largo: el test no puede proteger nada"
    return int(largo)


def _literales_por_columna():
    """`{columna: [(texto, línea)]}` — literales pasados directo y los de las constantes.

    Se leen las dos formas porque las dos fallaron: el desborde del MEM viajaba dentro de un
    dict de constantes (`MEM_TEMAS`) y el de `FUENTE_CONTEO` era una constante suelta usada
    como `source=`.
    """
    from modules.social_dev import social_sync

    arbol = ast.parse(inspect.getsource(social_sync))
    out = {c: [] for c in COLUMNAS}

    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            for kw in nodo.keywords:
                if kw.arg in out and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    out[kw.arg].append((kw.value.value, kw.value.lineno))

    # Constantes de módulo: `FUENTE_*` va a `source`; los valores de un `*_TEMAS` son
    # (tema, unidad) y van a `theme` y `unit`.
    for nombre in dir(social_sync):
        valor = getattr(social_sync, nombre)
        if nombre.startswith("FUENTE_") and isinstance(valor, str):
            out["source"].append((valor, 0))
        elif nombre.endswith("_TEMAS") and isinstance(valor, dict):
            for par in valor.values():
                if isinstance(par, (tuple, list)) and len(par) == 2:
                    out["theme"].append((str(par[0]), 0))
                    out["unit"].append((str(par[1]), 0))
    return out


def test_ningun_rotulo_desborda_su_columna():
    literales = _literales_por_columna()
    # Sin este control el barrido puede quedarse vacío y el test pasaría sin proteger nada,
    # que es exactamente cómo un guard deja de existir sin que nadie lo note.
    assert sum(len(v) for v in literales.values()) >= 10, (
        "el barrido no encontró rótulos: dejó de leer el módulo de sync")

    desbordan = [
        f"{col}({_largo(col)}): «{txt}» mide {len(txt)}"
        + (f" (línea {ln})" if ln else "")
        for col, pares in literales.items()
        for txt, ln in pares
        if len(txt) > _largo(col)
    ]
    assert not desbordan, (
        "estos rótulos no entran en su columna y Postgres aborta la transacción entera al "
        "comitear —SQLite no lo nota—:\n  " + "\n  ".join(desbordan))
