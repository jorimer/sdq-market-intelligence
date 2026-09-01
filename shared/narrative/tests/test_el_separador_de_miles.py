"""El guard leía «4,031 %» como 4,031 y marcaba como inventada una cifra servida.

**Medido en producción el 2026-09-01:** de las cinco marcas del día, **cuatro** eran esto.

    031.22%   ← la COLA de «4,031.22 %», porque la expresión no casaba el número entero
    445.16%   ← la cola de «3,445.16 %»
    4,031%    ← leído como 4,031 en vez de 4031
    3,445%    ← leído como 3,445 en vez de 3445

Las dos cifras existían y estaban servidas: la cobertura de provisiones sobre cartera vencida
del sector energía (4.031,22 %) y la del sistema (3.445,16 %). El modelo hasta lo decía en la
propia frase —«es el dato servido directamente en el campo…»— y el guard igual la marcaba.

**Un separador es decimal en una notación y de miles en la otra, y la plataforma escribe en
las dos.** `float(literal.replace(",", "."))` elige una y se equivoca en la mitad de los casos.

Es la misma familia que el «69 %» redondeado y el «132 %» de una razón servida: una cifra REAL
en una forma que el guard no reconocía. La pregunta ante una marca no es «¿el modelo
inventó?».
"""
import pytest

from shared.narrative.numeric_guard import (_CLAIM_UNIT, deterministic_uncited_figures,
                                            lecturas_de_la_cifra)

#: El contexto REAL que produjo las marcas: lo sirve el perfil sectorial de `shared/`.
CTX_ENERGIA = {"credito_del_sistema_al_sector_energia": {
    "cobertura_de_provision_sobre_vencida_del_sector_energia_pct": 4031.22,
    "mora_del_sector_energia_pct": 0.03}}


# ── La expresión tiene que casar el número ENTERO ─────────────────

@pytest.mark.parametrize("texto,esperado", [
    ("la cobertura es de 4,031.22%", ["4,031.22"]),
    ("llega a 3,445.16% —anclo esta cifra", ["3,445.16"]),
    ("asciende al 4,031%", ["4,031"]),
    ("coberturas de 3,445% y 395%", ["3,445", "395"]),
    ("el 4.031,22% en notación española", ["4.031,22"]),
    ("una mora de 0.87%", ["0.87"]),
])
def test_la_expresion_casa_el_numero_entero_y_no_su_cola(texto, esperado):
    """Sin la alternativa agrupada, el motor de expresiones avanzaba hasta casar «031.22» —
    una cifra que nadie escribió, marcada como inventada."""
    assert [m.group(1) for m in _CLAIM_UNIT.finditer(texto)] == esperado


# ── Las lecturas plausibles ───────────────────────────────────────

@pytest.mark.parametrize("literal,esperado", [
    # Los DOS separadores: el último es el decimal, sin ambigüedad.
    ("4,031.22", [(4031.22, 2)]),
    ("4.031,22", [(4031.22, 2)]),
    # Un separador repetido: agrupa.
    ("1.234.567", [(1234567.0, 0)]),
    # Exactamente tres dígitos detrás: AMBIGUO, las dos lecturas.
    ("4,031", [(4.031, 3), (4031.0, 0)]),
    # Dos dígitos: decimal y punto. La ambigüedad NO se abre de más.
    ("1,32", [(1.32, 2)]),
    ("0.87", [(0.87, 2)]),
    ("69", [(69.0, 0)]),
])
def test_las_lecturas_de_una_cifra_escrita(literal, esperado):
    assert lecturas_de_la_cifra(literal) == esperado


def test_una_cifra_ilegible_no_rompe_ni_inventa():
    assert lecturas_de_la_cifra("") == []
    assert lecturas_de_la_cifra("..") == []


# ── De punta a punta, con las frases REALES de producción ─────────

@pytest.mark.parametrize("frase", [
    "La cobertura de provisiones sobre cartera vencida es de 4,031.22%, derivada de la "
    "relación entre provisiones constituidas y saldo vencido.",
    "La cobertura de provisiones sobre cartera vencida asciende al 4,031% (el campo "
    "`cobertura_de_provision_sobre_vencida_del_sector_energia_pct` del contexto).",
    "Con una mora efectiva del 0.03% y cobertura de 4.031,22%.",
])
def test_las_frases_que_el_guard_marcaba_ya_NO_se_marcan(frase):
    assert deterministic_uncited_figures(CTX_ENERGIA, frase) == []


def test_el_CONTRA_CASO_una_cifra_inventada_sigue_marcada():
    """Sin esto, «no marcar nunca» pasaría todos los tests de arriba. La cura no puede ser
    dejar de mirar."""
    marcas = deterministic_uncited_figures(
        CTX_ENERGIA, "la cobertura llega a 7,777.77% según nuestro análisis")
    assert marcas, "una cifra que no está servida dejó de marcarse: el guard quedó ciego"
    assert "7,777.77%" in marcas[0]


def test_la_ambiguedad_que_se_ACEPTA_queda_dicha():
    """`4,031` admite dos lecturas y basta con que una esté respaldada. Es la política del
    módulo —filtro mecánico y barato, con el juez semántico aparte— y la apertura es acotada:
    solo grupos de exactamente tres dígitos, y solo la lectura de miles que ya era la correcta
    en la notación inglesa. Se declara acá para que no se descubra sola."""
    ctx_razon = {"bloque": {"razon_servida": 4.031}}
    # Servido 4,031 (la razón): la cita «4,031 %» pasa por la lectura decimal…
    assert deterministic_uncited_figures(ctx_razon, "la razón es de 4,031%") == []
    # …y con 4031 servido pasa por la lectura de miles. Las dos son legítimas.
    assert deterministic_uncited_figures(
        {"bloque": {"cobertura_pct": 4031.0}}, "la cobertura es de 4,031%") == []
