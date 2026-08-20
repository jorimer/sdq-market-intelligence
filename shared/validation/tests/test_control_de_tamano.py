"""REGLA ESTRUCTURAL: un motor que ordena sujetos declara contra qué CONTROL se lee su cifra.

**El caso, dos veces en dos motores distintos.** Un Gini sobre sujetos de tamaños muy
diferentes no distingue «el score ordena» de «el tamaño ordena y el score lo copia». Son
conclusiones opuestas y llevan a arreglos incompatibles.

- **`sector_intel` (IAI, Fase 3).** Contra intensidad de IED el índice daba −0,321 … y el
  tamaño SOLO daba −0,323: el signo era del deflactor. Contra nivel, +0,287 contra **+0,377**
  del tamaño solo. Veredicto: el IAI no agrega poder sobre el tamaño del sector.
- **`banking_score` (2026-08-19).** `solidez` daba −0,1944; comparando dentro del mismo tramo
  de tamaño, −0,0055 con el IC cruzando cero. El activo total solo ordena el desenlace con
  **+0,413**, mejor que el score entero. La conclusión anterior —«hay que corregir la curva del
  indicador de mayor peso»— era la equivocada.

**Por qué un test y no una lección.** En los dos casos el control cambió el veredicto, y en los
dos existía solo porque alguien se acordó. La doctrina del repo es explícita: cuando un defecto
se repite entre motores, la cura es un test estructural que lea el código con `ast` y exija la
regla o una excepción declarada.

**La regla, en tres partes.**

1. Todo motor de `shared.validation.frescura.MOTORES` declara `control_de_tamano`: o la clave
   donde el control VIAJA en su reporte, o un motivo de `MOTIVOS_SIN_CONTROL`. Nunca las dos,
   nunca ninguna.
2. `no_medido` obliga a nombrar la variable de tamaño que se usaría. Es un pendiente con
   nombre, no una exención — misma forma que `dato_pendiente` en `OBSTACULOS_BACKTEST`.
3. Una clave declarada tiene que EXISTIR en el código del eje. Un motor que promete un control
   y no lo emite deja publicada la cifra del score sin la vara que la acota, y ese silencio se
   lee como que el control se hizo.

**Qué queda fuera del glob, y por qué** (declarado, no omitido):

- Los **consumidores** de la cifra (`modules/*/products.py`, `shared/products/credenciales.py`,
  `reports/criteria_doc.py`): leen `gini` de un reporte ajeno, no producen el ordenamiento. La
  regla es para quien lo produce.
- Los **diagnósticos bajo demanda** que no persisten reporte: están en `DIAGNOSTICOS` con su
  motivo, y el test verifica que el archivo siga existiendo para que un renombre no los saque
  de la cuenta en silencio.
- La **cohorte histórica de quiebras** (`sib_historical_backtest.py`) y el **modelo de TPM**
  (`macro_monitor/tpm_modeling`), que viven fuera de `modules/*/validation/`. El primero no
  ordena por tamaño: cuenta anticipación sobre tres casos nombrados.
"""
import ast
import pathlib

import pytest

from shared.validation.control_tamano import MOTIVOS_SIN_CONTROL

RAIZ = pathlib.Path(__file__).resolve().parents[3]
MODULOS = RAIZ / "modules"

# Módulos que producen un Gini y NO son motores registrados: diagnósticos bajo demanda que no
# persisten nada. Entrar acá se defiende en revisión; producir un Gini y no estar ni acá ni en
# `MOTORES`, un test rojo.
DIAGNOSTICOS = {
    "banking_score/validation/composicion.py": (
        "diagnóstico bajo demanda que NO persiste reporte. Es, además, el que produjo la "
        "evidencia de esta regla: computa el control por tamaño él mismo "
        "(`activos_totales_como_score`) y estratifica por tramo de tamaño."
    ),
    "banking_score/validation/recalibracion.py": (
        "diagnóstico bajo demanda que NO persiste reporte. Compara dos versiones del MISMO "
        "score sobre el MISMO panel: el tamaño es idéntico en las dos ramas, así que no puede "
        "producir la diferencia que mide."
    ),
}


def _motores():
    import app.main  # noqa: F401 — auto-registra los motores reales
    from shared.validation.frescura import MOTORES

    return sorted(MOTORES.items())


def _emite_gini(ruta: pathlib.Path) -> bool:
    """True si el módulo escribe una clave `gini` — o sea, publica un ordenamiento."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    return any(isinstance(n, ast.Constant) and n.value in ("gini", "gini_ci")
               for n in ast.walk(arbol))


def _literales(paquete: pathlib.Path) -> set:
    """Cadenas literales del paquete, SIN el sitio donde vive la declaración.

    Sin esa exclusión el test se satisface solo: la clave declarada aparece en el mismo
    `operations.py` que la declara, así que un motor podía prometer `control_inexistente` y
    pasar. Lo descubrió una mutación deliberada — la única forma de saber si un guard muerde.
    """
    out = set()
    for ruta in paquete.rglob("*.py"):
        if "/tests/" in str(ruta):
            continue
        texto_registro = ruta.read_text(encoding="utf-8")
        if "registrar_motor(" in texto_registro:
            continue  # es el sitio de la declaración, no puede ser su propia prueba
        try:
            arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — un fuente roto ya rompe otros gates
            continue
        out |= {n.value for n in ast.walk(arbol)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    return out


# ── 1. Nadie calla ────────────────────────────────────────────────

def test_todo_motor_declara_contra_que_control_se_lee_su_cifra():
    sin_declarar = [eje for eje, m in _motores() if m.control_de_tamano is None]
    assert not sin_declarar, (
        f"Estos motores publican un ordenamiento sin declarar su control por tamaño: "
        f"{sin_declarar}. Un motor que calla su control se lee como si lo hubiera hecho, y "
        "eso ya dio vuelta el veredicto en `sector_intel` y en `banking_score`."
    )


def test_o_el_control_viaja_o_se_declara_por_que_no_corresponde():
    """Nunca las dos, nunca ninguna: «lo medimos» y «no corresponde» no son lo mismo."""
    ambiguos = []
    for eje, m in _motores():
        c = m.control_de_tamano
        if c is None:
            continue
        if bool(c.clave) == bool(c.motivo):
            ambiguos.append(f"{eje}: clave={c.clave!r} motivo={c.motivo!r}")
    assert not ambiguos, (
        "Cada motor declara exactamente una de las dos cosas: "
        f"{ambiguos}"
    )


def test_el_motivo_sale_de_la_lista_cerrada():
    inventados = []
    for eje, m in _motores():
        c = m.control_de_tamano
        if c and c.motivo and c.motivo not in MOTIVOS_SIN_CONTROL:
            inventados.append(f"{eje}: {c.motivo!r}")
    assert not inventados, (
        f"Motivos fuera de `MOTIVOS_SIN_CONTROL`: {inventados}. Un motivo nuevo se agrega al "
        "catálogo con su explicación, no se inventa en el sitio de registro."
    )


# ── 2. «No medido» es un pendiente con nombre ─────────────────────

def test_no_medido_obliga_a_nombrar_la_variable_de_tamano():
    """Sin nombrar la variable, `no_medido` es «pendiente» — y pendiente no es un motivo."""
    mudos = []
    for eje, m in _motores():
        c = m.control_de_tamano
        if c and c.motivo == "no_medido" and not (c.variable or "").strip():
            mudos.append(eje)
    assert not mudos, (
        f"Estos motores declaran `no_medido` sin decir con QUÉ variable se mediría: {mudos}. "
        "Una brecha sin nombre no se puede cerrar ni presupuestar."
    )


# ── 3. Una clave declarada existe de verdad ───────────────────────

def test_la_clave_declarada_existe_en_el_codigo_del_eje():
    """El defecto que este repo ya vio siete veces: el guard que promete y no emite.

    Un motor que declara `clave="control_solo_tamano"` y no la escribe en ningún lado publica
    la cifra del score sin su vara, y la declaración lo tapa.
    """
    huecas = []
    for eje, m in _motores():
        c = m.control_de_tamano
        if not (c and c.clave):
            continue
        paquete = MODULOS / eje
        if not paquete.is_dir():
            huecas.append(f"{eje}: no existe el paquete `modules/{eje}`")
            continue
        if c.clave not in _literales(paquete):
            huecas.append(f"{eje}: declara `{c.clave}` y no aparece en `modules/{eje}`")
    assert not huecas, (
        f"Controles declarados que el código no emite: {huecas}"
    )


# ── 4. Qué queda afuera del glob ──────────────────────────────────

def test_todo_modulo_que_publica_un_gini_esta_declarado():
    """El glob mira `modules/*/validation/*.py`: quien produce el ordenamiento."""
    ejes = {eje for eje, _m in _motores()}
    huerfanos = []
    for ruta in sorted(MODULOS.glob("*/validation/*.py")):
        if ruta.name == "__init__.py" or not _emite_gini(ruta):
            continue
        relativa = str(ruta.relative_to(MODULOS))
        if relativa in DIAGNOSTICOS or ruta.parts[-3] in ejes:
            continue
        huerfanos.append(relativa)
    assert not huerfanos, (
        f"Estos módulos publican un Gini y no tienen motor registrado ni están declarados "
        f"como diagnóstico: {huerfanos}"
    )


def test_los_diagnosticos_declarados_siguen_existiendo():
    """Un renombre no puede sacar un módulo de la cuenta sin que nadie se entere."""
    fantasmas = [rel for rel in DIAGNOSTICOS if not (MODULOS / rel).is_file()]
    assert not fantasmas, (
        f"Declarados como diagnóstico pero el archivo ya no existe: {fantasmas}. "
        "Sacalos de `DIAGNOSTICOS` o corregí la ruta."
    )


# ── 5. El control de banca no puede DESAPARECER ───────────────────

def test_el_reporte_de_banca_trae_la_clave_del_control_siempre(monkeypatch):
    """Un guard sin su insumo no falla: DESAPARECE. Acá se le quita la base a propósito.

    El reporte tiene que seguir trayendo `control_solo_tamano` —con su motivo adentro— en vez
    de omitir la clave, que es como el control se pierde sin que ninguna superficie lo note.
    """
    from modules.banking_score.validation import report as mod

    class _Obs:
        def __init__(self, score, det):
            self.score, self.tier, self.deteriorated = score, "Sólida", det
            self.triggers = ("roa_negativo_sostenido",) if det else ()
            self.bank_id, self.period_end = "B1", None

    obs = [_Obs(90.0, True)] * 5 + [_Obs(50.0, False)] * 15
    monkeypatch.setattr(mod, "derive_observations", lambda *_a, **_k: obs)

    rep = mod.build_backtest_report(db=None, n_boot=20)
    assert "control_solo_tamano" in rep, (
        "El reporte perdió la clave del control al faltarle la base. Un control que "
        "desaparece deja la cifra del score publicada sin su vara."
    )
    assert rep["control_solo_tamano"]["motivo"], "Si no se computó, tiene que decir por qué."
    assert rep["control_solo_tamano"]["nota"] == mod.NOTA_CONTROL_TAMANO


@pytest.mark.parametrize("eje", ["banking_score", "sector_intel"])
def test_los_dos_motores_que_ya_lo_tienen_no_pueden_perderlo(eje):
    """Regresión sobre los dos casos que motivaron la regla."""
    declarado = dict(_motores())[eje].control_de_tamano
    assert declarado is not None and declarado.clave == "control_solo_tamano", (
        f"`{eje}` midió su control por tamaño y cambió su veredicto con él. Quitarlo es "
        "volver al estado que esta regla existe para impedir."
    )
