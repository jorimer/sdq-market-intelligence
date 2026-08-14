"""El nombre del archivo identifica la naturaleza del documento — y no colisiona.

Pedido del dueño (2026-08-13): «cada archivo generado debe tener un nombre que permita
identificar la naturaleza del reporte». Detrás del pedido de forma había un defecto de fondo:
la ruta de productos nombraba con (sector, nivel, período) y **descartaba el sujeto**, así que
el Deep Dive de dos entidades del mismo corte producía el MISMO nombre y el segundo pisaba al
primero en la carpeta de descargas.

Esquema aprobado: ``SDQ_<Eje>_<Naturaleza>_<Sujeto>_<Período>.<ext>``.
"""
import pytest

from shared.products.filenames import (
    EJE_LABELS, SUJETO_SISTEMA, TIER_NATURALEZA, content_disposition, eje_label,
    report_filename, slug,
)
from shared.products.registry import PRODUCT_CATALOG
from shared.products.tiers import ProductTier


# ── Lo que el defecto costaba: dos entidades, un solo archivo ──

def test_dos_entidades_del_mismo_corte_no_colisionan():
    """SENSOR DE REGRESIÓN. Antes ambas daban `SDQ_banking_deep_dive_2025-12-31.pdf`."""
    bpd = report_filename(sector_key="banking", naturaleza="Deep-Dive",
                          sujeto="Banco Popular Dominicano", periodo="2025-12-31")
    res = report_filename(sector_key="banking", naturaleza="Deep-Dive",
                          sujeto="Banreservas", periodo="2025-12-31")
    assert bpd != res
    assert bpd == "SDQ_Banca_Deep-Dive_Banco-Popular-Dominicano_2025-12-31.pdf"


def test_dos_naturalezas_de_la_misma_entidad_no_colisionan():
    """Un Insight y un Deep Dive del mismo banco y corte son documentos distintos."""
    nombres = {report_filename(sector_key="banking", naturaleza=n, sujeto="Banreservas",
                               periodo="2025-12-31")
               for n in TIER_NATURALEZA.values()}
    assert len(nombres) == len(TIER_NATURALEZA)


def test_dos_cortes_de_la_misma_entidad_no_colisionan():
    a = report_filename(sector_key="banking", naturaleza="Deep-Dive", sujeto="BPD",
                        periodo="2025-09-30")
    b = report_filename(sector_key="banking", naturaleza="Deep-Dive", sujeto="BPD",
                        periodo="2025-12-31")
    assert a != b


def test_la_muestra_no_pisa_al_informe_real():
    real = report_filename(sector_key="banking", naturaleza="Deep-Dive", sujeto="Banco Demo",
                           periodo="2024-12-31")
    demo = report_filename(sector_key="banking", naturaleza="Deep-Dive", sujeto="Banco Demo",
                           periodo="2024-12-31", muestra=True)
    assert real != demo and "Muestra" in demo


# ── El esquema ──

@pytest.mark.parametrize("kwargs,esperado", [
    ({"sector_key": "banking", "naturaleza": "Informe de Calificación Completa",
      "sujeto": "Banco Popular Dominicano", "periodo": "2025-12-31"},
     "SDQ_Banca_Calificacion-Completa_Banco-Popular-Dominicano_2025-12-31.pdf"),
    ({"sector_key": "insurance", "naturaleza": "Deep-Dive",
      "sujeto": "Humano Seguros, S.A.", "periodo": "2025-12-31"},
     "SDQ_Seguros_Deep-Dive_Humano-Seguros-SA_2025-12-31.pdf"),
    ({"sector_key": "pension", "naturaleza": "Pulse", "sujeto": SUJETO_SISTEMA,
      "periodo": "2025-12-31"},
     "SDQ_Pensiones_Pulse_Sistema_2025-12-31.pdf"),
    # Word conserva el esquema; solo cambia la extensión.
    ({"sector_key": "banking", "naturaleza": "Insight", "sujeto": "BPD",
      "periodo": "2025-12-31", "fmt": "docx"},
     "SDQ_Banca_Insight_BPD_2025-12-31.docx"),
    # Campos ausentes se OMITEN: el bug anterior emitía "..._None.pdf".
    ({"sector_key": "banking", "naturaleza": "Criterios de Calificación",
      "periodo": "2026-08-13"},
     "SDQ_Banca_Criterios-de-Calificacion_2026-08-13.pdf"),
])
def test_esquema(kwargs, esperado):
    assert report_filename(**kwargs) == esperado


def test_nunca_emite_none_ni_campos_vacios():
    n = report_filename(sector_key=None, naturaleza="Criterios", sujeto=None, periodo=None)
    assert "None" not in n and "__" not in n and n == "SDQ_Criterios.pdf"


# ── Higiene: el nombre viaja por una cabecera HTTP y aterriza en Windows/OneDrive ──

@pytest.mark.parametrize("crudo", [
    "Compañía Eléctrica de Peñuelas · S.A.",
    "DataWatch · Sistema Bancario",
    "Asociación Popular de Ahorros y Préstamos",
    'Banco "X" / Y \\ Z: *?<>|',
])
def test_solo_ascii_seguro(crudo):
    n = report_filename(sector_key="banking", naturaleza="Deep-Dive", sujeto=crudo)
    assert n.isascii(), n
    # Ni separadores de ruta ni caracteres que Windows rechaza, ni comillas que romperían
    # el propio header Content-Disposition.
    assert not set(n) & set('/\\:*?"<>|·'), n
    assert " " not in n


def test_el_guion_bajo_solo_separa_campos():
    """`_` es el separador de CAMPOS: si se cuela dentro de un valor, el nombre deja de ser
    parseable de un vistazo (`Zonas_Francas` leería como dos campos)."""
    n = report_filename(sector_key="free_zones", naturaleza="Deep-Dive",
                        sujeto="Zona_Franca Las Américas", periodo="2025-12-31")
    assert n == "SDQ_Zonas-Francas_Deep-Dive_Zona-Franca-Las-Americas_2025-12-31.pdf"
    assert n.count("_") == 4


def test_nombre_largo_no_rompe_el_guardado():
    """Un filename >255 bytes falla al guardar en varios sistemas. La razón social es el
    campo que puede venir larguísimo."""
    n = report_filename(sector_key="banking", naturaleza="Deep-Dive", sujeto="Á" * 500,
                        periodo="2025-12-31")
    assert len(n.encode("utf-8")) < 255
    assert n.endswith("_2025-12-31.pdf"), "el período no debe perderse al recortar"


def test_content_disposition_bien_formado():
    n = report_filename(sector_key="banking", naturaleza="Deep-Dive", sujeto="BPD")
    assert content_disposition(n) == f'attachment; filename="{n}"'


# ── Cobertura: ningún eje se queda sin etiqueta ──

def test_todo_eje_del_catalogo_declara_su_etiqueta():
    """PRUEBA NEGATIVA de cobertura: un eje nuevo sin etiqueta caería al slug inglés de su
    clave (`free_zones` → `free-zones`) sin que nadie lo note. Que falle acá."""
    faltan = [e.sector_key for e in PRODUCT_CATALOG if e.sector_key not in EJE_LABELS]
    assert not faltan, f"ejes del catálogo sin etiqueta en EJE_LABELS: {faltan}"


def test_las_etiquetas_de_eje_son_distinguibles():
    """Dos ejes con la misma etiqueta harían colisionar sus informes de sistema."""
    usadas = [EJE_LABELS[e.sector_key] for e in PRODUCT_CATALOG]
    assert len(usadas) == len(set(usadas)), f"etiquetas de eje repetidas: {usadas}"


def test_todo_nivel_declara_su_naturaleza():
    faltan = [t.value for t in ProductTier if t.value not in TIER_NATURALEZA]
    assert not faltan, f"niveles sin naturaleza declarada: {faltan}"


def test_eje_desconocido_degrada_en_vez_de_romper():
    """Una descarga nunca debe fallar por un rótulo faltante."""
    assert eje_label("sector_inventado") == "sector-inventado"
    assert eje_label(None) == ""


@pytest.mark.parametrize("crudo,esperado", [
    ("S.A.", "SA"), ("C. por A.", "C-por-A"), ("  ", ""), (None, ""),
    ("2025-12-31", "2025-12-31"), ("Ñoño", "Nono"),
])
def test_slug(crudo, esperado):
    assert slug(crudo) == esperado
