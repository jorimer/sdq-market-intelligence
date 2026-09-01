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


# ── 6. El control no puede desaparecer en NINGÚN motor que lo declare ──

def test_todos_los_motores_publican_su_control():
    """La cuenta, computada del registro. Si baja, alguien quitó un control.

    Cuando esta regla se escribió eran DOS de ocho, y se fueron computando: seguros
    (primas), pensiones (AUM), comercio (exportado), IRMP (PIB), ESG (población) y, el
    2026-09-01, `social_dev` — que era el último y estaba afuera por DATO, no por diseño.
    Su población por región se conectó desde el SISDOM, así que hoy no queda ninguno.
    """
    todos = sorted(eje for eje, _m in _motores())
    publican = sorted(eje for eje, m in _motores()
                      if m.control_de_tamano and m.control_de_tamano.clave)
    assert publican == todos, (
        f"quedaron motores sin publicar su control: {sorted(set(todos) - set(publican))}. "
        "Un motor que calla su control se lee como si lo hubiera hecho.")


def test_un_motor_sin_control_declara_QUE_le_falta_y_cual():
    """«No medido» sin decir qué falta es «pendiente», y pendiente no es un motivo.

    Hoy no hay ninguno en ese estado (lo asegura el test de arriba). La regla vive igual,
    porque el que se agregue mañana entra por acá: un motor nuevo que no pueda computar su
    control tiene que nombrar la variable que usaría y el obstáculo real, no encogerse de
    hombros. Es la misma forma que `dato_pendiente` en `OBSTACULOS_BACKTEST`.
    """
    for eje, m in _motores():
        motivo = m.control_de_tamano.motivo if m.control_de_tamano else None
        if motivo != "no_medido":
            continue
        assert m.control_de_tamano.variable, (
            f"{eje} declara «no_medido» sin nombrar la variable de tamaño que usaría.")
        assert m.control_de_tamano.nota, (
            f"{eje} declara «no_medido» sin nombrar el obstáculo real.")


def test_el_control_de_seguros_viaja_dentro_de_la_senal(monkeypatch):
    """Pegado al Gini que acota, no en otra clave del reporte: si no, no se lee junto."""
    from modules.insurance_intel.validation import backtest as mod

    obs = [mod.Obs(slug=f"a{i}", period="2020", score=float(i), fwd=float(i), label=i % 2)
           for i in range(12)]
    control = mod.control_por_tamano(
        obs, {f"a{i}": {"2020": float(100 - i)} for i in range(12)}, gini_del_score=0.2)
    assert control["variable"] == "primas_suscritas"
    assert control["n"] == 12
    assert control["gini"] is not None
    assert control["veredicto"]


def test_un_panel_sin_tamano_declara_el_motivo_en_vez_de_devolver_cero():
    """«No se pudo computar» y «el tamaño no ordena» son cosas distintas."""
    from shared.validation.control_tamano import medir_control_de_tamano

    salida = medir_control_de_tamano([None, None, None], [1, 0, 1], 0.3, variable="activos")
    assert salida["gini"] is None
    assert salida["motivo"]
    assert salida["n"] == 0


def test_el_veredicto_del_control_compara_magnitudes_no_signos():
    """El caso del IAI: el deflactor producía −0,32 entero, con el signo del índice."""
    from shared.validation.control_tamano import (
        VEREDICTO_SCORE_SUPERA, VEREDICTO_TAMANO_ALCANZA, medir_control_de_tamano,
    )

    tamanos = [float(i) for i in range(20)]
    # El tamaño ordena PERFECTO y con signo negativo (los chicos son los eventos).
    fuerte = [1 if i < 10 else 0 for i in range(20)]
    alcanza = medir_control_de_tamano(tamanos, fuerte, gini_del_score=0.10, variable="t",
                                      n_boot=50)
    assert alcanza["gini"] == 1.0
    assert alcanza["el_tamano_alcanza_al_score"] is True, (
        "Un control de |Gini| 1,0 contra un score de 0,10 tiene que alcanzarlo: si comparara "
        "signos en vez de magnitudes, el +1,0 no 'alcanzaría' a un score positivo chico."
    )
    assert alcanza["veredicto"] == VEREDICTO_TAMANO_ALCANZA

    # Ahora un tamaño que casi no ordena: el score sí agrega por encima de él.
    debil = [i % 2 for i in range(20)]
    supera = medir_control_de_tamano(tamanos, debil, gini_del_score=0.80, variable="t",
                                     n_boot=50)
    assert abs(supera["gini"]) < 0.8
    assert supera["el_tamano_alcanza_al_score"] is False
    assert supera["veredicto"] == VEREDICTO_SCORE_SUPERA


# ── 7. Los dos estados que la corrida REAL obligó a agregar ───────

def test_el_empate_no_se_reporta_como_ventaja_del_score():
    """El caso que casi publica una conclusión falsa (seguros, 2026-08-19).

    La señal de underwriting daba 0,2575 y el tamaño solo 0,2404 — una diferencia de 0,017
    con los IC casi superpuestos. Un `>=` estricto llamaba a eso «el score supera al tamaño»,
    que en un documento comercial se lee como que la credencial mide algo que el tamaño no.
    """
    from shared.validation.control_tamano import VEREDICTO_EMPATE, medir_control_de_tamano

    tamanos = [float(i) for i in range(40)]
    labels = [1 if i % 3 == 0 else 0 for i in range(40)]
    salida = medir_control_de_tamano(tamanos, labels, gini_del_score=0.2575,
                                     ic_del_score=[0.1237, 0.3946], variable="primas",
                                     n_boot=50)
    assert salida["gini"] is not None
    if salida["gini_ci"] and 0.1237 <= salida["gini"] <= 0.3946:
        assert salida["empata_con_el_score"] is True
        assert salida["veredicto"] == VEREDICTO_EMPATE


def test_un_control_sobre_OTRO_panel_se_niega_a_comparar():
    """El caso real de pensiones: 96 de 1.590 observaciones con tamaño, y aun así veredicto.

    Los activos son trimestrales y los retornos mensuales. Comparar un Gini de 1.590
    observaciones con uno de 96 pone dos universos uno al lado del otro y engaña.
    """
    from shared.validation.control_tamano import VEREDICTO_OTRO_PANEL, medir_control_de_tamano

    tamanos = [float(i) if i < 10 else None for i in range(100)]
    labels = [i % 2 for i in range(100)]
    salida = medir_control_de_tamano(tamanos, labels, gini_del_score=0.16,
                                     ic_del_score=[0.10, 0.22], variable="activos", n_boot=50)
    assert salida["n"] == 10 and salida["n_del_score"] == 100
    assert salida["cobertura_del_panel"] == 0.1
    assert salida["comparable"] is False
    assert salida["veredicto"] == VEREDICTO_OTRO_PANEL
    assert salida["el_tamano_alcanza_al_score"] is False, (
        "Un control incomparable no puede afirmar que el tamaño alcanza: sería una "
        "conclusión sacada de otro universo."
    )


def test_el_N_del_score_viaja_al_lado_del_N_del_control():
    """Sin los dos N, nadie nota que se están comparando dos paneles distintos."""
    from shared.validation.control_tamano import medir_control_de_tamano

    salida = medir_control_de_tamano([1.0, 2.0, 3.0, 4.0], [1, 0, 1, 0], 0.2,
                                     variable="t", n_boot=20)
    assert salida["n"] == 4 and salida["n_del_score"] == 4
    assert salida["cobertura_del_panel"] == 1.0 and salida["comparable"] is True


def test_pensiones_alinea_el_tamano_al_periodo_sin_inventar_valores():
    """Último valor CONOCIDO en o antes del período: una regla declarada, no interpolación."""
    from modules.pension_intel.validation.backtest import _vigente

    serie = {"2024-03": 100.0, "2024-06": 120.0}
    assert _vigente(serie, "2024-05") == 100.0   # arrastra el trimestre anterior
    assert _vigente(serie, "2024-06") == 120.0
    assert _vigente(serie, "2024-01") is None    # antes del primer dato NO inventa


# ── Todas las ramas de retorno traen las MISMAS claves ─────────────────────────

def test_toda_rama_de_medir_control_devuelve_el_mismo_contrato():
    """El hueco entra por la rama que alguien olvidó.

    `medir_control_de_tamano` tiene una rama temprana para el panel degenerado —sin tamaños,
    o con una sola clase del desenlace— y omitía `el_tamano_alcanza_al_score` y
    `empata_con_el_score`. Un consumidor que lee con `.get()` recibía None, que en un
    `bool()` es False: o sea «el tamaño NO lo explica», afirmado por un control que nunca
    se computó. Es el `stale=null` otra vez — «no sé» leído como «está bien».

    Lo encontró un test de banca que recorre TODAS las familias de desenlace, incluida una
    cuya regla no dispara nunca. Un test que mirara solo la señal titular no lo habría visto.
    """
    from shared.validation.control_tamano import medir_control_de_tamano

    sano = medir_control_de_tamano([float(i) for i in range(12)], [i % 2 for i in range(12)],
                                   gini_del_score=0.2, variable="x", n_boot=50)
    degenerados = {
        "sin tamaños": ([None] * 12, [i % 2 for i in range(12)]),
        "una sola clase del desenlace": ([float(i) for i in range(12)], [1] * 12),
        "panel vacío": ([], []),
    }
    for etiqueta, (tamanos, labels) in degenerados.items():
        salida = medir_control_de_tamano(tamanos, labels, gini_del_score=0.2,
                                         variable="x", n_boot=50)
        faltan = set(sano) - set(salida)
        assert not faltan, f"la rama «{etiqueta}» omite {sorted(faltan)}"
        assert salida["el_tamano_alcanza_al_score"] is False
        assert salida["empata_con_el_score"] is False
        assert "no evaluable" in salida["veredicto"]
