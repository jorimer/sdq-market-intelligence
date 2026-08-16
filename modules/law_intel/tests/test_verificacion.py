"""La comprobación corre donde están los datos y no muta el expediente."""
from modules.law_intel.bindings import Binding
from modules.law_intel.verificacion import ANTIGUEDAD_MAXIMA_ANIOS, comprobar, informe

BS = {"1.8": Binding("1.8", "s.viva", "one", "menor", "propuesto"),
      "2.1": Binding("2.1", "s.vieja", "one", "menor", "propuesto"),
      "3.25": Binding("3.25", "s.vacia", "mhe", "mayor", "propuesto"),
      "3.9": Binding("3.9", "s.x", "pefa", "mayor", "descartado", motivo_descarte="m")}


def proveedor(codigo):
    return {"s.viva": [("2023", 1.0), ("2024", 2.0)],
            "s.vieja": [("2011", 1.0)]}.get(codigo, [])


def test_clasifica_cada_serie():
    r = {c.indicador: c.resultado for c in comprobar(BS, proveedor, "2025")}
    assert r["1.8"] == "verificable"
    assert r["2.1"] == "congelada", "existe pero su último dato no mide el corte"
    assert r["3.25"] == "vacia"
    assert "3.9" not in r, "un binding descartado ya se evaluó; no se re-comprueba"


def test_solo_lo_verificable_promueve():
    cs = {c.indicador: c for c in comprobar(BS, proveedor, "2025")}
    assert cs["1.8"].promueve
    assert not cs["2.1"].promueve and not cs["3.25"].promueve


def test_un_proveedor_que_falla_no_rompe_el_barrido():
    def rompe(_):
        raise RuntimeError("serie caída")
    assert all(c.resultado == "vacia" for c in comprobar(BS, rompe, "2025"))


def test_el_umbral_de_antiguedad_es_el_declarado():
    justo = str(2025 - ANTIGUEDAD_MAXIMA_ANIOS)
    bs = {"1.8": Binding("1.8", "s", "one", "menor", "propuesto")}
    assert comprobar(bs, lambda _: [(justo, 1.0)], "2025")[0].resultado == "verificable"
    viejo = str(2025 - ANTIGUEDAD_MAXIMA_ANIOS - 1)
    assert comprobar(bs, lambda _: [(viejo, 1.0)], "2025")[0].resultado == "congelada"


def test_el_informe_dice_cuanta_cobertura_se_gana(monkeypatch):
    monkeypatch.setattr("modules.law_intel.verificacion.cargar_bindings", lambda _: BS)
    r = informe("x", proveedor, "2025")
    assert r["promovibles_a_verificado"] == ["1.8"]
    assert r["ganancia_de_cobertura"] == 1
    assert "NO muta el expediente" in r["nota"]
