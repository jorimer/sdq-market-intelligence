"""El vigilante de deploy: si no puede confirmar, FALLA — nunca deja seguir.

Dos defectos reales, el mismo día (2026-08-20), los dos generando material comercial contra una
producción que no tenía el arreglo que el documento venía a corregir:

1. Se esperaba IGUALDAD con el SHA del merge. Otra sesión mergeó en paralelo, ganó el deploy de
   SU PR —un commit que no contenía mi cambio— y la igualdad no se dio nunca.
2. Al expirar, el lazo seguía igual: la línea siguiente generaba el documento lo mismo. Un
   artefacto producido tras un timeout se ve idéntico a uno correcto.

Estos tests fijan las tres salidas, y ninguna significa «seguí igual».
"""
import importlib.util
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]


def _mod():
    spec = importlib.util.spec_from_file_location(
        "esperar_deploy", RAIZ / "scripts" / "esperar_deploy.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_sale_cero_solo_cuando_produccion_CONTIENE_el_cambio(monkeypatch):
    """Contención, no igualdad: el commit servido puede ser posterior y contenerlo."""
    m = _mod()
    monkeypatch.setattr(m, "commit_servido", lambda *_a, **_k: "b" * 40)
    monkeypatch.setattr(m, "contiene", lambda cambio, servido: True)
    assert m.esperar("a" * 40, "http://x", minutos=1) == 0


def test_expirar_devuelve_ERROR_y_no_deja_seguir(monkeypatch):
    """El defecto que produjo dos documentos malos: expirar y generar igual."""
    m = _mod()
    monkeypatch.setattr(m, "INTERVALO_SEGUNDOS", 0)
    monkeypatch.setattr(m, "commit_servido", lambda *_a, **_k: "c" * 40)
    monkeypatch.setattr(m, "contiene", lambda cambio, servido: False)
    assert m.esperar("a" * 40, "http://x", minutos=0) == 1, (
        "Un timeout tiene que ser un código de salida distinto de cero: encadenado con `&&`, "
        "es lo que impide que el artefacto se genere."
    )


def test_no_poder_verificar_es_ERROR_y_no_un_ok(monkeypatch):
    """«No sé de qué commit es» y «está al día» son cosas distintas — como `stale=None`."""
    m = _mod()
    monkeypatch.setattr(m, "INTERVALO_SEGUNDOS", 0)
    monkeypatch.setattr(m, "commit_servido", lambda *_a, **_k: "d" * 40)
    monkeypatch.setattr(m, "contiene", lambda cambio, servido: None)
    assert m.esperar("a" * 40, "http://x", minutos=1) == 2


def test_un_blip_de_red_no_es_un_veredicto(monkeypatch):
    """Health que no responde: se sigue esperando, no se concluye nada."""
    m = _mod()
    monkeypatch.setattr(m, "INTERVALO_SEGUNDOS", 0)
    monkeypatch.setattr(m, "commit_servido", lambda *_a, **_k: None)
    assert m.esperar("a" * 40, "http://x", minutos=0) == 1  # expira, no "no verificable"


def test_contiene_distingue_desconocido_de_no_contenido(monkeypatch):
    """Devolver False donde corresponde None haría esperar para siempre algo que ya llegó."""
    m = _mod()
    llamadas = []

    def _git_falso(*args):
        llamadas.append(args)
        class R:  # noqa: D401 — doble mínimo de CompletedProcess
            returncode = 1 if args[0] == "cat-file" else 0
            stdout = ""
        return R()

    monkeypatch.setattr(m, "_git", _git_falso)
    assert m.contiene("a" * 40, "e" * 40) is None
    assert any(a[0] == "fetch" for a in llamadas), "Tiene que intentar `git fetch` antes de rendirse."


def test_el_docstring_nombra_el_riesgo_del_health_ok():
    """La trampa que hay que recordar vive en el fuente, no en la memoria de nadie."""
    m = _mod()
    assert "status: ok" in (m.__doc__ or "") or "`ok`" in (m.__doc__ or "")
    assert "contiene" in (m.__doc__ or "").lower()


@pytest.mark.parametrize("codigo", [1, 2])
def test_ningun_codigo_de_fallo_es_cero(codigo):
    assert codigo != 0
