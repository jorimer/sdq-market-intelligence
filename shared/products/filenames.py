"""Nombre de archivo de todo documento descargable — un solo constructor.

**Por qué existe.** Cada ruta de descarga armaba su nombre a mano y cada una con un esquema
distinto, así que una carpeta de dossier era ilegible. Tres defectos concretos, todos reales:

1. El informe por entidad de Banca llegaba como ``reporte_<uuid>.pdf``: el backend construía
   un nombre correcto y lo mandaba en el ``Content-Disposition``, y el frontend lo descartaba.
   El cliente terminaba renombrando los archivos a mano.
2. El reporte de producto era ``SDQ_{sector}_{tier}_{periodo}`` y **descartaba el scope**. El
   Deep Dive de dos bancos distintos del mismo corte producía el MISMO nombre: al bajar el
   segundo, pisaba al primero. Eso no es cosmética, es pérdida de un archivo.
3. Las muestras y el informe forense salían sin período.

**El esquema.** ``SDQ_<Eje>_<Naturaleza>_<Sujeto>_<Período>.<ext>``, decidido por el dueño
(2026-08-13) para que al ordenar la carpeta por nombre los documentos se agrupen POR TIPO:

    SDQ_Banca_Calificacion-Completa_Banco-Popular-Dominicano_2025-12-31.pdf
    SDQ_Banca_Criterios_2026-08-13.pdf
    SDQ_Banca_Deep-Dive_Banreservas_2025-12-31.pdf
    SDQ_Seguros_Deep-Dive_Humano-Seguros_2025-12-31.pdf

``_`` separa campos y ``-`` une palabras dentro de un campo: mezclar los dos separadores es lo
que hace el nombre parseable de un vistazo. Los campos vacíos se omiten (Criterios no tiene
sujeto) en vez de emitir ``_None_``.

**ASCII estricto, a propósito.** Los nombres viajan por una cabecera HTTP y aterrizan en
Windows, macOS, OneDrive y adjuntos de correo. Un ``·``, una tilde o un espacio sobreviven en
un sistema y se rompen o se escapan en otro. La portada del documento lleva la tipografía
correcta; el nombre de archivo lleva la que no se rompe.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

# Eje → etiqueta del archivo. En español y compacta: `banking`/`free_zones` no le dicen nada a
# quien recibe el PDF, y `display_name` del catálogo ("SDQ Banking Intelligence") es una marca
# comercial, no un campo de nombre de archivo.
#
# La cobertura la EXIGE `test_filenames.py` contra `PRODUCT_CATALOG`: un eje nuevo que no
# declare su etiqueta rompe el test en vez de caer en silencio al slug inglés de su clave.
EJE_LABELS = {
    "banking": "Banca",
    "insurance": "Seguros",
    "pension": "Pensiones",
    "macro": "Macro",
    "monetary_policy": "Politica-Monetaria",
    "trade": "Comercio",
    "tourism": "Turismo",
    "free_zones": "Zonas-Francas",
    "energy": "Energia",
    "telecom": "Telecom",
    "construction": "Construccion",
    "agribusiness": "Agronegocios",
    "esg": "ESG",
    "economic_structure": "Estructura-Economica",
    "social_dev": "Desarrollo-Social",
    # El sujeto de este eje es un INSTRUMENTO NORMATIVO, no un país ni una firma.
    "law": "Evaluacion-de-Leyes",
}

# Nivel comercial → naturaleza del documento. Espeja `TIER_LABELS` del generador de banca,
# que es de banca; acá vale para los quince ejes.
TIER_NATURALEZA = {"pulse": "Pulse", "insight": "Insight", "deep_dive": "Deep-Dive"}

# Sujeto de un informe de sistema: el documento no habla de una entidad. Sin esto el campo
# quedaba vacío y dos informes de sistema de distinto eje se distinguían solo por el eje.
SUJETO_SISTEMA = "Sistema"

# Topes por campo. Un nombre de archivo por encima de ~255 bytes falla al guardar en varios
# sistemas; el sujeto es el campo que puede venir largo (razón social completa) y el motor de
# research puede traer una pregunta entera como naturaleza.
_MAX_CAMPO = 60
_MAX_TOTAL = 200


def slug(texto: Optional[str], *, max_len: int = _MAX_CAMPO) -> str:
    """Un campo del nombre: ASCII, palabras unidas por ``-``, sin separador de campo.

    El ``_`` se convierte a ``-`` a propósito: es el separador de CAMPOS, así que dejarlo
    pasar dentro de un valor rompe el parseo del nombre ("Zonas_Francas" leería como dos
    campos). Devuelve "" si no queda nada — el llamador omite el campo.
    """
    if not texto:
        return ""
    plano = unicodedata.normalize("NFKD", str(texto))
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    plano = plano.replace("ñ", "n").replace("Ñ", "N")
    # El punto de una abreviatura se BORRA, no se convierte en separador: "Humano Seguros,
    # S.A." daba "Humano-Seguros-S-A", donde la forma jurídica ocupa tres tokens y compite
    # visualmente con el nombre. Borrarlo da "Humano-Seguros-SA" sin perder información —
    # y no se recorta la razón social, que es lo que evitaría distinguir dos entidades.
    plano = re.sub(r"(?<=[A-Za-z])\.", "", plano)
    plano = re.sub(r"[^A-Za-z0-9]+", "-", plano)
    return plano.strip("-")[:max_len].strip("-")


# "Informe de Calificación Completa" → "Calificacion-Completa". Los rótulos vienen de la
# PORTADA, donde "Informe de…" es correcto; en el nombre de archivo es puro ruido (todos son
# informes) y desplaza al sujeto fuera de la vista en un explorador de archivos.
_PREFIJO_REDUNDANTE = re.compile(r"^Informe(-de)?-", re.I)


def eje_label(sector_key: Optional[str]) -> str:
    """Etiqueta del eje. Un eje sin etiqueta declarada cae a su clave saneada — degradar es
    mejor que romper una descarga, y el test estructural es el que impide que pase."""
    if not sector_key:
        return ""
    return EJE_LABELS.get(sector_key) or slug(sector_key)


def report_filename(
    *,
    naturaleza: str,
    sector_key: Optional[str] = None,
    eje: Optional[str] = None,
    sujeto: Optional[str] = None,
    periodo: Optional[str] = None,
    fmt: str = "pdf",
    muestra: bool = False,
) -> str:
    """``SDQ_<Eje>_<Naturaleza>_<Sujeto>_<Período>.<fmt>`` con los campos vacíos omitidos.

    Args:
        naturaleza: qué ES el documento ("Deep-Dive", "Calificacion-Completa", "DataWatch").
            Es el campo que el dueño pidió que el nombre identifique.
        sector_key: clave del eje; se traduce con ``EJE_LABELS``. Alternativamente ``eje``
            para superficies fuera del catálogo (research, brand_intel).
        sujeto: entidad analizada. Para un informe de sistema, ``SUJETO_SISTEMA``.
        periodo: corte de los datos. Si el documento no tiene corte (Criterios), el llamador
            pasa la fecha de generación — un documento sin fecha en el nombre es
            indistinguible de su propia versión anterior, que es el problema que resuelve.
        muestra: marca el ejemplar de conversión. Va pegado a la naturaleza y no al principio
            para no romper el agrupamiento por tipo, que es lo que el esquema busca.
    """
    nat = _PREFIJO_REDUNDANTE.sub("", slug(naturaleza)) or slug(naturaleza)
    if muestra:
        nat = f"{nat}-Muestra" if nat else "Muestra"
    campos = [c for c in ("SDQ", eje_label(sector_key) or slug(eje), nat,
                          slug(sujeto), slug(periodo)) if c]
    nombre = "_".join(campos)[:_MAX_TOTAL].rstrip("_-")
    ext = slug(fmt, max_len=8).lower() or "pdf"
    return f"{nombre}.{ext}"


def content_disposition(filename: str) -> str:
    """Cabecera lista para servir. Punto único para que ninguna ruta improvise el formato."""
    return f'attachment; filename="{filename}"'
