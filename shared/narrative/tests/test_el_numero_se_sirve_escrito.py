"""El formato del número no se delega: se sirve escrito.

**Lo que lo obligó.** El contexto servía flotantes pelados —`6823.5`, `1239546.0`— y cada
generación elegía cómo escribirlos. En un boletín REAL de 16 páginas convivieron tres
convenciones de miles: 76 cifras con coma, 8 con punto y 4 con espacio.

El saneador corrige el caso ilegible («6.823.5», que con punto decimal se lee como seis coma
ochocientos veintitrés) DESPUÉS de escrito. Pero no puede tocar «1.239.546»: reescribirlo
podría equivocar la magnitud por mil, y un saneador que arriesga eso es peor que la
inconsistencia que arregla. La única cura que no adivina es no delegar el formato.

Es la misma regla del encabezado de cada país: un hecho computable no se delega a quien puede
copiarlo mal.
"""
import pytest

from shared.narrative.formato import numero_para_prosa


# ── El formateador ────────────────────────────────────────────────
@pytest.mark.parametrize("valor,unidad,esperado", [
    (1239546.0, None, "1,239,546"),   # el que el saneador NO puede arreglar después
    (6823.5, None, "6,823.5"),
    (2891.62, "puntos", "2,891.6"),
    (61506, None, "61,506"),
    (16.9448, "%", "16.94"),          # la precisión sale de la unidad, no del flotante
    (2.3398, "%", "2.34"),
    (-0.1768, "%", "-0.18"),
    (7.85, "%", "7.85"),
    (0.0, "%", "0.00"),               # un cero REAL se escribe; no se confunde con ausencia
])
def test_escribe_en_la_convencion_de_casa(valor, unidad, esperado):
    assert numero_para_prosa(valor, unidad) == esperado


def test_un_ausente_devuelve_None_y_no_un_cero():
    """En un indicador inverso el cero es una afirmación fuerte y falsa. Ya se publicó una vez."""
    assert numero_para_prosa(None) is None
    assert numero_para_prosa(float("nan")) is None
    assert numero_para_prosa(True) is None      # un bool no es una medición


def test_nunca_usa_punto_como_separador_de_MILES():
    """La convención de casa es punto DECIMAL: un punto agrupando vuelve la cifra ilegible."""
    import re

    for v in (1239546.0, 6823.5, 61506, 2891.62):
        escrito = numero_para_prosa(v)
        assert not re.search(r"\d\.\d{3}", escrito), f"{v} salió como {escrito}"


# ── Llega a los contextos ─────────────────────────────────────────
def test_el_contexto_REGIONAL_sirve_el_numero_escrito():
    from modules.regional_banking.ai_context import _valor

    class _Fila:
        metric, value, period_end, source = "mora_90_colocaciones", 2.3398, None, "CMF Chile"
        norma_contable = "CMF Chile — Compendio 2022"
        meta = {"unit": "%", "nombre": "Morosidad de 90 días o más"}

    d = _valor(_Fila())
    assert d["valor_texto"] == "2.34"
    assert d["valor"] == 2.3398, "el crudo tiene que seguir ahí: el guard lo necesita"


def test_el_contexto_de_SISTEMA_sirve_los_promedios_escritos():
    from modules.banking_score.reports.narrative import _build_system_context

    ctx = _build_system_context(
        "boletin_regional", "Sistema", "2025-12-31",
        {"sector_averages": {"cobertura_provisiones_avg": 136.4823,
                             "hhi_ingresos_avg": 5303.82}})
    escritos = ctx["promedios_sistema_texto"]
    assert escritos["cobertura_provisiones_avg"] == "136.48%", (
        "sin la unidad pegada, 136,48 se escribe igual sea un porcentaje o un múltiplo — y "
        "se narró como «136,48 veces el uno»")
    assert escritos["hhi_ingresos_avg"] == "5,303.8"
    assert ctx["promedios_sistema"]["hhi_ingresos_avg"] == 5303.82, (
        "el dict crudo no se reemplaza: lo consumen otras superficies y el guard numérico")


def test_las_plantillas_del_boletin_piden_copiar_la_forma_escrita():
    from shared.narrative.claude_engine import THIN_TEMPLATES

    for k in ("boletin_sistema_pais", "boletin_armonizado"):
        assert "COMO VIENEN ESCRITAS" in THIN_TEMPLATES[k], (
            f"«{k}» sirve el número escrito y no le pide al modelo que lo copie: servir el "
            "dato no alcanza, hay que pedirlo")


# ── Y el guard sigue respaldando la cifra escrita ─────────────────
@pytest.mark.parametrize("escrito,crudo", [
    ("1,239,546", 1239546.0),
    ("6,823.5", 6823.5),
    ("16.94", 16.9448),
])
def test_el_guard_RECONOCE_la_cifra_ya_formateada(escrito, crudo):
    """Si el guard no leyera los separadores, servir el número escrito convertiría cada cifra
    real en una marca de «cifra sin respaldo» — el arreglo sería peor que el defecto."""
    from shared.narrative.numeric_guard import lecturas_de_la_cifra

    lecturas = [v for v, _dec in lecturas_de_la_cifra(escrito)]
    assert any(abs(v - crudo) < 0.01 or abs(v - round(crudo, 2)) < 0.01 for v in lecturas), (
        f"«{escrito}» se leyó como {lecturas}, y el valor servido es {crudo}")


# ── Los grupos de pares y el umbral que nadie verificó ────────────
def test_los_grupos_de_PARES_tambien_llegan_escritos():
    """El HHI por tipo salió «5 040» en un boletín real: este bloque no pasaba por el
    formateador, y arreglar solo los promedios del sistema dejaba la mitad afuera."""
    from modules.banking_score.reports.narrative import _build_system_context

    ctx = _build_system_context(
        "boletin_regional", "Sistema", "2025-12-31",
        {"sector_averages": {"hhi_ingresos_avg": 5303.82},
         "peer_groups": {"banco_ahorro_credito": {"hhi_ingresos_avg": 5040.3}}})
    assert ctx["grupos_de_pares_texto"]["banco_ahorro_credito"]["hhi_ingresos_avg"] == "5,040.3"
    assert ctx["grupos_de_pares"]["banco_ahorro_credito"]["hhi_ingresos_avg"] == 5040.3, (
        "el crudo no se reemplaza: lo necesita el guard numérico")


def test_el_contexto_SIRVE_las_anclas_con_las_que_esta_plataforma_lee_el_HHI():
    """El boletín publicó «superiores a 2 500 concentración elevada, sobre 5 000 muy alta».

    Esas son (aproximadamente) las bandas antimonopolio del DOJ, y esta plataforma las
    DESCARTÓ tras medirlas: con esos cortes el 62,8% del panel quedaba en cero y las diez
    asociaciones de ahorros y préstamos sacaban cero por concentrarse en vivienda, que es su
    objeto social. El modelo las escribió de memoria porque nadie le sirvió las verdaderas.
    """
    from modules.banking_score.reports.narrative import _build_system_context

    ctx = _build_system_context(
        "boletin_regional", "Sistema", "2025-12-31",
        {"sector_averages": {"hhi_ingresos_avg": 5303.82}})
    leer = ctx["como_leer_el_hhi"]
    assert "POR ESTRATO" in leer["regla"]
    assert "NO cites umbrales" in leer["regla"]
    assert leer["anclas_por_tipo"]["aap"] == {"p10_mejor": 2600.0, "p90_peor": 4150.0}
    assert leer["sin_estrato_propio"]["p90_peor"] == 6400.0


def test_las_anclas_salen_del_REGISTRO_y_no_de_una_copia():
    """Dos fuentes para el mismo hecho es como una se queda atrás: si alguien recalibra los
    estratos, el contexto tiene que moverse con ellos."""
    from modules.banking_score.reports.narrative import _anclas_del_hhi
    from modules.banking_score.scoring.hhi_estratos import ANCLAS

    servidas = _anclas_del_hhi()["anclas_por_tipo"]
    assert set(servidas) == set(ANCLAS)
    for tipo, (p10, p90) in ANCLAS.items():
        assert servidas[tipo] == {"p10_mejor": p10, "p90_peor": p90}


def test_la_plantilla_de_RD_pide_la_forma_escrita_y_veta_el_umbral_de_memoria():
    from shared.narrative.claude_engine import THIN_TEMPLATES

    t = THIN_TEMPLATES["boletin_rd"]
    assert "COMO VIENEN ESCRITAS" in t
    assert "NO cites umbrales de memoria" in t
