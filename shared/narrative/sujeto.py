"""La regla del SUJETO, en un solo lugar: toda porción nombra su población.

**El caso que la fundó.** `insurance_intel/ai_context.py` pasaba al modelo una clave
`concentracion_top4_pct` cuyo valor era la suma de los cuatro RAMOS de mayor peso. La tabla
del PDF lo rotulaba bien; la clave que veía el modelo había perdido el sujeto, y justo debajo
venía `aseguradoras_activas: 26`. El Deep Dive salió afirmando que «cuatro compañías
concentran el 87,1% de las primas». El número era correcto: lo que se perdió camino al modelo
fue de qué era.

**Por qué el vocabulario vive acá y no dentro del test que lo estrenó.** La regla nació
vigilando el contexto de IA (`tests/test_regla_sujeto_en_contexto.py`), pero el contexto no es
la única superficie que le pasa cifras rotuladas a un lector: las ALERTAS también, y con menos
revisión humana que ningún otro artefacto —ya salieron, no hay que ir a buscarlas—. Dos copias
del vocabulario divergen; una sola no puede. Este repo ya pagó cinco veces el mismo guard
presente en un motor y ausente en otro.
"""
from __future__ import annotations

from typing import Tuple

# Palabras que denotan una porción de un total. Una clave con alguna de ellas afirma
# implícitamente «de qué», y ese «de qué» tiene que estar escrito.
PORCION: Tuple[str, ...] = (
    "concentracion", "concentration", "cuota", "share", "participacion", "hhi", "cr5",
    "cr10", "peso_",
)

# Sujetos admitidos: la población sobre la que se computa la porción.
SUJETOS: Tuple[str, ...] = (
    "ramo", "ramos", "compania", "companias", "empresa", "empresas", "entidad",
    "entidades", "banco", "bancos", "aseguradora", "aseguradoras", "afp", "activos",
    "provincia", "province", "typology", "tipologia", "export", "chapter", "sector",
    "origin", "origen", "region", "generation", "generacion",
    "producto", "product", "geography", "personas", "danos", "salud",
    "sin_clasificar", "broadband", "sqm", "metric", "market", "mercado",
    # La concentración de cartera se computa sobre DEUDORES — la población que la regla no
    # conocía y que es justo la que el modelo reatribuía: publicó la concentración de los
    # diez mayores deudores como si fuera de entidades.
    "deudor", "deudores",
)

# Marcador de exención declarada, para las superficies que se leen con `ast`.
EXENCION = "sujeto-ok:"


def es_porcion(nombre: str) -> bool:
    """¿La clave *nombre* afirma una porción de un total?"""
    return any(p in nombre.lower() for p in PORCION)


def nombra_su_poblacion(nombre: str) -> bool:
    """¿La clave *nombre* cumple la regla? Una clave que no es porción la cumple por
    vacuidad: la regla solo tiene algo que exigirle a las que afirman «de qué»."""
    bajo = nombre.lower()
    if not es_porcion(bajo):
        return True
    return any(s in bajo for s in SUJETOS)
