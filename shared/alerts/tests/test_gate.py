"""Los seis vetos, y el test estructural que impide esquivarlos.

Un veto que se puede saltear no es un veto. Los tests de abajo prueban cada uno contra el
defecto real que lo originó; :func:`test_nadie_construye_un_AlertEvent_a_mano` prueba que no
hay un camino alternativo a la bandeja del cliente — que es la pregunta que este repo aprendió
a hacerse después de encontrar cinco veces el mismo guard presente en un motor y ausente en
otro.
"""
import ast
import dataclasses
import pathlib

import pytest

from shared.alerts.gate import juzgar
from shared.alerts.reglas import AlertEvent

RAIZ = pathlib.Path(__file__).resolve().parents[3]


BASE = AlertEvent(
    codigo="umbral", sector_key="banking", subject="b1", periodo="2026-Q2",
    severidad="alta", titulo="Cobertura de provisiones: Banco A",
    cuerpo="La cobertura está en 91,00%, por debajo del umbral de 100,00%.",
    basis="crisis RD 2003", relaciones={"metrica": "cobertura", "direccion": "por_debajo"},
    valores={"cobertura": 91.0}, procedencia={"cobertura": "live"}, frescura=True)


def ev(**kw) -> AlertEvent:
    """Un evento sano, con lo que el test quiera romper. Se usa ``replace`` sobre un base
    inmutable: cada caso cambia UNA cosa y el resto queda igual, así el motivo del veredicto
    nunca es ambiguo."""
    return dataclasses.replace(BASE, **kw)


def test_el_caso_sano_publica():
    """Si el caso sano no publicara, todo lo de abajo pasaría por la razón equivocada."""
    assert juzgar(ev()).publica is True


# ── 1 · Frescura: tres estados, no dos ───────────────────────────────────────

@pytest.mark.parametrize("frescura,motivo", [
    (True, None),
    (False, "frescura_vencida"),
    (None, "frescura_indeterminada"),
])
def test_frescura_tiene_TRES_estados(frescura, motivo):
    """``None`` no publica. «No sé de cuándo es» y «está al día» son cosas distintas, y
    confundirlas puso 19 días en producción un Gini calculado con un score que ya no
    existía."""
    v = juzgar(ev(frescura=frescura))
    assert v.motivo == motivo
    assert v.publica is (motivo is None)


def test_el_veto_de_frescura_explica_la_diferencia():
    """El motivo tiene que distinguir «vencida» de «no sé»: piden acciones distintas."""
    assert "no sé" in juzgar(ev(frescura=None)).detalle.lower()


# ── 2 · Brecha: ninguna cifra ausente sostiene una afirmación ────────────────

def test_una_cifra_ausente_veta():
    v = juzgar(ev(valores={"cobertura": None}))
    assert v.motivo == "cifra_ausente"


def test_la_alerta_de_BRECHA_es_la_excepcion():
    """Es la única regla cuyo insumo legítimo es la ausencia: existe para declararla."""
    v = juzgar(ev(codigo="brecha", valores={"solvencia": None},
                  titulo="Brecha: Solvencia",
                  cuerpo="Solvencia dejó de tener dato para Banco A al 2026-Q2.",
                  relaciones={"metrica": "solvencia", "direccion": "pierde"}))
    assert v.publica is True


# ── 3 · Comparabilidad: solo se ordena lo comparable ─────────────────────────

def test_una_posicion_sin_universo_no_publica():
    """Un score armado sobre 3 de 5 dimensiones no rankea contra uno de 5. Ya se publicó
    «7 de 35» así, contando scores que no eran comparables."""
    v = juzgar(ev(relaciones={"metrica": "score", "direccion": "cae", "posicion": 4}))
    assert v.motivo == "universo_no_declarado"


def test_una_posicion_CON_universo_publica():
    v = juzgar(ev(relaciones={"metrica": "score", "direccion": "cae", "posicion": 4},
                  universo="17 entidades de banca múltiple con las 5 dimensiones"))
    assert v.publica is True


# ── 4 · Sujeto: toda porción nombra su población ─────────────────────────────

def test_una_porcion_sin_poblacion_no_publica():
    """«Cuatro compañías concentran el 87,1%» eran cuatro RAMOS. La clave había perdido el
    sujeto y el lector lo reatribuyó a la población más cercana."""
    v = juzgar(ev(valores={"concentracion_top10_pct": 51.0}))
    assert v.motivo == "sujeto_ausente"
    assert "concentracion_top10_pct" in v.detalle


def test_la_misma_porcion_CON_su_poblacion_publica():
    assert juzgar(ev(valores={"concentracion_top10_deudores_pct": 51.0})).publica is True


def test_una_clave_que_no_es_porcion_pasa_por_vacuidad():
    """La regla solo tiene algo que exigirle a las claves que afirman «de qué»."""
    assert juzgar(ev(valores={"solvencia_pct": 9.8})).publica is True


# ── 5 · Relación: la dirección se computa, no se narra ───────────────────────

def test_afirmar_una_direccion_sin_computarla_no_publica():
    """La glosa sobrevivió dos veces a corregir el número. Si el texto dice «por debajo», el
    dato tiene que venir de `relaciones`, no del criterio de quien escribió la plantilla."""
    v = juzgar(ev(relaciones={"metrica": "cobertura"}))     # sin `direccion`
    assert v.motivo == "relacion_no_computada"


def test_un_texto_sin_direccion_no_necesita_relacion():
    v = juzgar(ev(cuerpo="Cobertura de provisiones de Banco A: 91,00% al 2026-Q2.",
                  titulo="Cobertura", relaciones={"metrica": "cobertura"}))
    assert v.publica is True


# ── 6 · Vocabulario: una señal no es un pronóstico ───────────────────────────

@pytest.mark.parametrize("texto", [
    "El modelo predice el deterioro de la entidad.",
    "Alta probabilidad de impago en los próximos trimestres.",
    "Riesgo de quiebra elevado.",
])
def test_el_vocabulario_predictivo_no_publica(texto):
    """`docs/CLAIMS_COMERCIALES.md` lo prohíbe para todo lo que no tenga backtest contra un
    desenlace externo. Una regla de umbral es una señal a monitorear."""
    v = juzgar(ev(cuerpo=texto, relaciones={"metrica": "x", "direccion": "por_debajo"}))
    assert v.motivo == "vocabulario_predictivo"


def test_ninguna_plantilla_del_modulo_usa_vocabulario_prohibido():
    """No alcanza con vetar en tiempo de ejecución: si una plantilla lo trae, cada evento que
    la use nace vetado y el eje queda mudo sin que nadie entienda por qué."""
    from shared.alerts import reglas
    from shared.alerts.gate import PROHIBIDO

    plantillas = [v for k, v in vars(reglas).items()
                  if k.startswith("TXT_") and isinstance(v, str)]
    assert plantillas, "el barrido no encontró ninguna plantilla"
    for txt in plantillas:
        assert not [p for p in PROHIBIDO if p in txt.lower()], txt


# ── El camino único ──────────────────────────────────────────────────────────

def _fuentes_que_emiten():
    """Todo archivo que pueda poner un evento en el canal.

    **Qué queda afuera** es la pregunta que hay que hacerle a este glob. No alcanza con
    `modules/*/alerts_producer.py`: un eje puede registrar su productor desde otro archivo,
    así que además se barre cualquier módulo que llame a ``register_producer``.
    """
    rutas = set((RAIZ / "shared" / "alerts").glob("*.py"))
    rutas |= set(RAIZ.glob("modules/*/alerts_producer.py"))
    for ruta in RAIZ.glob("modules/*/*.py"):
        if "register_producer" in ruta.read_text(encoding="utf-8"):
            rutas.add(ruta)
    return sorted(r for r in rutas if r.name != "reglas.py")


def test_el_barrido_encuentra_las_fuentes():
    """Un glob que no encuentra nada deja el test estructural en verde sin proteger nada."""
    nombres = {r.name for r in _fuentes_que_emiten()}
    assert "motor.py" in nombres
    assert "alerts_producer.py" in nombres, "el productor de banca quedó fuera del barrido"


@pytest.mark.parametrize("ruta", _fuentes_que_emiten(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_nadie_construye_un_AlertEvent_a_mano(ruta):
    """Solo ``reglas.py`` instancia ``AlertEvent``.

    Es lo que hace que el gate sea inevitable: una regla construye el evento pasando por sus
    guardas de ``None``, y todo lo demás COMPONE reglas. Un productor que armara el evento a
    mano se saltearía esas guardas sin que ningún test de comportamiento lo notara — el
    evento saldría bien formado y con la cifra equivocada.
    """
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    ofensas = [n.lineno for n in ast.walk(arbol)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "AlertEvent"]
    assert not ofensas, (
        f"{ruta.relative_to(RAIZ)} construye AlertEvent en la(s) línea(s) {ofensas}. "
        f"Los eventos se crean en shared/alerts/reglas.py, que es donde viven las guardas "
        f"de dato ausente.")
