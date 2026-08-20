"""El adaptador de banca: del panel de precursores a eventos de alerta.

**Este módulo no calibra umbrales y este test no los prueba.** Lo que se verifica es la
traducción, y sobre todo las tres situaciones que ``signal_panel`` distingue y que el canal
de alertas tiene que respetar:

- ``activa``      → hay algo que avisar
- ``sin_activar`` → se evaluó y no disparó ⇒ la condición está RESUELTA
- ``sin_dato``    → nadie pudo mirarla; **no es lo mismo que estar bien**

Confundir las dos últimas es el defecto caro: si «sin dato» se diera por resuelto, el aviso
se repetiría en cuanto el dato volviera, y ese repique diría «pasó algo» cuando lo único que
pasó es que se pudo mirar de nuevo.
"""
import datetime as _dt

import pytest

from modules.banking_score import alerts_producer as ap


def _fila(code, estado, value=None, threshold=None, label=None, umbral_significa=""):
    return {"code": code, "label": label or code.replace("_", " ").capitalize(),
            "estado": estado, "value": value, "threshold": threshold,
            "umbral_significa": umbral_significa}


def _bloque(period, paneles, banks=None):
    return {"period": period, "panels": paneles, "banks": banks or [],
            "summary": {}, "profiles": {}}


HOY = _dt.date.today()
PERIODO = (HOY - _dt.timedelta(days=40)).isoformat()      # fresco
PERIODO_VIEJO = (HOY - _dt.timedelta(days=400)).isoformat()


class _DB:
    """Doble de sesión: el productor no consulta la base en estos tests — se le entrega el
    panel ya calculado. Lo único que consultaría son los nombres de las entidades sin
    banderas, y acá vienen en el panel."""

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return []

    def query(self, *a, **k):
        return _DB._Q()


@pytest.fixture()
def sin_db(monkeypatch):
    """El productor no toca la base en estos tests: se le da el panel ya calculado."""
    monkeypatch.setattr(ap, "_periodo_anterior", lambda db, actual: None)


def _correr(monkeypatch, actual, anterior=None):
    from modules.banking_score import early_warning

    def fake(db, period=None):
        return anterior if (period is not None and anterior is not None) else actual

    monkeypatch.setattr(early_warning, "compute_alerts", fake)
    return ap.producir(_DB())


# ── La traducción ────────────────────────────────────────────────────────────

def test_una_senal_activa_produce_un_evento_con_la_direccion_COMPUTADA(monkeypatch, sin_db):
    """La dirección sale de comparar valor y umbral, no de transcribir qué regla la encendió.
    Una alerta que se equivoca de dirección es peor que ninguna."""
    panel = {"b1": [_fila("brecha_provisiones", "activa", 91.0, 100.0,
                          "Brecha de provisiones", "cobertura por debajo de 100%")]}
    prod = _correr(monkeypatch, _bloque(PERIODO, panel,
                                        banks=[{"bank_id": "b1", "name": "Banco A",
                                                "band": "media", "alerts": [
                                                    {"code": "brecha_provisiones",
                                                     "severity": "alta"}]}]))
    umbral = [e for e in prod.eventos if e.codigo == "umbral"]
    assert len(umbral) == 1
    e = umbral[0]
    assert e.relaciones["direccion"] == "por_debajo"
    assert e.severidad == "alta"
    assert e.subject == "b1"
    assert "Banco A" in e.cuerpo
    assert e.basis                                  # nunca suena "porque sí"


def test_lo_evaluado_y_NO_disparado_cuenta_como_resuelto(monkeypatch, sin_db):
    panel = {"b1": [_fila("solvencia_piso", "sin_activar", 14.0, 10.0)]}
    prod = _correr(monkeypatch, _bloque(PERIODO, panel))
    assert prod.eventos == [] or all(e.codigo != "umbral" for e in prod.eventos)
    assert "banking:b1:umbral:solvencia_piso" in prod.evaluadas


def test_SIN_DATO_no_entra_a_evaluadas(monkeypatch, sin_db):
    """El defecto caro. Dar por resuelta una condición que nadie pudo mirar es cómo un guard
    sin su input deja de fallar y DESAPARECE."""
    panel = {"b1": [_fila("solvencia_piso", "sin_dato")]}
    prod = _correr(monkeypatch, _bloque(PERIODO, panel))
    assert "banking:b1:umbral:solvencia_piso" not in prod.evaluadas


def test_perder_el_dato_es_una_alerta_de_BRECHA(monkeypatch):
    """Que un eje haya perdido su dato es noticia para quien vigila la entidad."""
    from modules.banking_score import early_warning

    anterior = (HOY - _dt.timedelta(days=130)).isoformat()
    hoy = _bloque(PERIODO, {"b1": [_fila("solvencia_piso", "sin_dato")]})
    ayer = _bloque(anterior, {"b1": [_fila("solvencia_piso", "sin_activar", 14.0, 10.0)]})

    monkeypatch.setattr(early_warning, "compute_alerts",
                        lambda db, period=None: ayer if period else hoy)
    monkeypatch.setattr(ap, "_periodo_anterior",
                        lambda db, actual: _dt.date.fromisoformat(anterior))

    prod = ap.producir(_DB())
    brechas = [e for e in prod.eventos if e.codigo == "brecha"]
    assert len(brechas) == 1
    assert brechas[0].relaciones["direccion"] == "pierde"


def test_sin_dato_SIN_periodo_anterior_no_inventa_una_brecha(monkeypatch, sin_db):
    """Sin estado anterior no hay transición: solo una foto sin dato, que es el estado y no
    una noticia."""
    panel = {"b1": [_fila("solvencia_piso", "sin_dato")]}
    prod = _correr(monkeypatch, _bloque(PERIODO, panel))
    assert [e for e in prod.eventos if e.codigo == "brecha"] == []


# ── La polaridad invertida de la banda ───────────────────────────────────────

def test_la_banda_se_juzga_con_la_polaridad_CORRECTA(monkeypatch):
    """`ensemble_score` devuelve 100 = ningún precursor activo, así que «alta» es la MEJOR
    banda. Si la dirección saliera de comparar rótulos, un deterioro se publicaría como
    mejora — y el propio motor documenta que el original se leía al revés."""
    from modules.banking_score import early_warning

    hoy = _bloque(PERIODO, {"b1": [_fila("solvencia_piso", "sin_activar", 14.0, 10.0)]},
                  banks=[{"bank_id": "b1", "name": "Banco A", "band": "baja", "alerts": []}])
    ayer = _bloque("2026-03-31", {"b1": [_fila("solvencia_piso", "sin_activar", 14.0, 10.0)]},
                   banks=[{"bank_id": "b1", "name": "Banco A", "band": "alta", "alerts": []}])

    monkeypatch.setattr(early_warning, "compute_alerts",
                        lambda db, period=None: ayer if period else hoy)
    monkeypatch.setattr(ap, "_periodo_anterior", lambda db, actual: _dt.date(2026, 3, 31))

    prod = ap.producir(_DB())
    banda = [e for e in prod.eventos if e.codigo == "banda"]
    assert len(banda) == 1
    assert banda[0].relaciones["direccion"] == "deterioro", (
        "alta → baja es un DETERIORO: la polaridad de ensemble_score está invertida")


def test_una_entidad_sin_banderas_no_pierde_su_banda(monkeypatch, sin_db):
    """`banks` solo trae entidades con banderas activas. Sin el default, una entidad que se
    recupera se leería como que perdió su banda en vez de como que mejoró."""
    panel = {"b1": [_fila("solvencia_piso", "sin_activar", 14.0, 10.0)]}
    assert ap._bandas(_bloque(PERIODO, panel))["b1"] == ap.BANDA_SIN_ALERTAS


# ── Frescura ─────────────────────────────────────────────────────────────────

def test_un_periodo_viejo_no_es_fresco(monkeypatch, sin_db):
    panel = {"b1": [_fila("brecha_provisiones", "activa", 91.0, 100.0)]}
    prod = _correr(monkeypatch, _bloque(PERIODO_VIEJO, panel))
    assert all(e.frescura is False for e in prod.eventos)


def test_un_periodo_ilegible_deja_la_frescura_INDETERMINADA(monkeypatch, sin_db):
    """`None`, no `False` ni `True`. «No sé de cuándo es» es su propio estado, y el gate lo
    veta igual — pero el motivo que registra es otro, y pide otra acción."""
    panel = {"b1": [_fila("brecha_provisiones", "activa", 91.0, 100.0)]}
    prod = _correr(monkeypatch, _bloque("último trimestre", panel))
    assert all(e.frescura is None for e in prod.eventos)


def test_la_frescura_de_un_periodo_reciente_es_True():
    assert ap._frescura(PERIODO) is True
    assert ap._frescura(PERIODO_VIEJO) is False
    assert ap._frescura(None) is None
    assert ap._frescura("no es una fecha") is None


# ── La regla del sujeto ──────────────────────────────────────────────────────

def test_la_concentracion_viaja_con_su_POBLACION(monkeypatch, sin_db):
    """La concentración de cartera se computa sobre DEUDORES. Sin el sujeto en la clave, el
    gate la veta — y con razón: así se publicó la concentración de los diez mayores deudores
    como si fuera de entidades."""
    from shared.alerts.gate import juzgar

    panel = {"b1": [_fila("concentracion_credito", "activa", 51.0, 50.0)]}
    prod = _correr(monkeypatch, _bloque(PERIODO, panel))
    umbral = [e for e in prod.eventos if e.codigo == "umbral"]
    assert umbral, "la señal de concentración no produjo evento"
    assert "deudores" in next(iter(umbral[0].valores))
    assert juzgar(umbral[0]).publica is True


def test_todo_evento_del_productor_PASA_el_gate(monkeypatch, sin_db):
    """El adaptador no puede fabricar eventos que el gate rechace por forma: un eje que se
    auto-veta queda mudo sin que nadie entienda por qué."""
    from shared.alerts.gate import juzgar

    panel = {"b1": [
        _fila("brecha_provisiones", "activa", 91.0, 100.0, "Brecha de provisiones"),
        _fila("morosidad_nivel", "activa", 8.0, 5.0, "Morosidad sobre el umbral de su tipo"),
        _fila("concentracion_credito", "activa", 51.0, 50.0, "Concentración de cartera"),
    ]}
    prod = _correr(monkeypatch, _bloque(PERIODO, panel))
    assert prod.eventos
    for e in prod.eventos:
        v = juzgar(e)
        assert v.publica, f"{e.codigo}/{e.relaciones.get('metrica')} vetado: {v.motivo}"


def test_valor_igual_al_umbral_no_publica_una_direccion_inventada(monkeypatch, sin_db):
    """Justo encima del umbral no se puede afirmar de qué lado está."""
    panel = {"b1": [_fila("solvencia_piso", "activa", 10.0, 10.0)]}
    prod = _correr(monkeypatch, _bloque(PERIODO, panel))
    assert [e for e in prod.eventos if e.codigo == "umbral"] == []


# ── El registro ──────────────────────────────────────────────────────────────

def test_banca_esta_registrada_como_productor():
    from shared.alerts.motor import registered_sectors

    ap.register()
    assert "banking" in registered_sectors()
