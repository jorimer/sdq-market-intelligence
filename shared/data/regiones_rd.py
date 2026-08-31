"""La regionalización de la República Dominicana, con su procedencia.

**Por qué existe este archivo.** El libro de crédito de la SIB trae una región por provincia;
la ENCFT del BCRD publica el mercado laboral por dominio geográfico. Cruzarlos permite decir
cómo son las condiciones de empleo del territorio donde una entidad presta — una lectura que
ningún banco puede armar con su propio libro. Pero cruzar dos nomenclaturas sin comprobar que
hablan de lo mismo es cómo se le atribuye a una provincia el dato de otra.

**Qué se comprobó.** Las dos usan la MISMA regionalización legal:

* El Decreto 710-04 (30 de junio de 2004) crea **10 Regiones de Desarrollo** sobre las 32
  unidades territoriales del país (31 provincias más el Distrito Nacional).
* El catálogo IHSN del diseño muestral de la ENCFT declara que sus dominios de estimación se
  redujeron a «las cuatro grandes regiones geográficas de la República Dominicana: Gran Santo
  Domingo u Ozama, Norte o Cibao, Sur y Este», construidas sobre esas 10 regiones.
* La partición que trae el cubo de la SIB —observada en producción— coincide con esa
  agregación PROVINCIA POR PROVINCIA en las 32.

**Qué NO es.** No es la macrorregionalización oficial: el Decreto agrupa las 10 regiones en
TRES macrorregiones (Cibao, Suroeste, Sureste), con Ozama dentro de Sureste. Ni la SIB ni la
ENCFT usan esa de tres; las dos separan Ozama y trabajan con cuatro. La hoja de la ENCFT dice
«según macro regiones» en sentido laxo, y ese término estuvo a punto de servir de ancla falsa.

**Cómo se mantiene honesto.** La composición se declara acá una vez, con su fuente, y un test
estructural la contrasta contra lo que el cubo de la SIB trae en producción: si la SIB
reagrupa una provincia, el test lo dice en vez de que el cruce empiece a mentir en silencio.
"""
from __future__ import annotations

from typing import Dict, Tuple

#: Fuente de la composición, para que el informe pueda declararla.
PROCEDENCIA = ("Decreto 710-04 (Regiones de Desarrollo) agregadas en los cuatro dominios de "
               "estimación que declara el diseño muestral de la ENCFT")

#: Las 10 Regiones de Desarrollo y sus provincias. Los nombres van SIN TILDES y en mayúsculas
#: porque así los publica el cubo de la SIB: normalizar acá evitaría comparar contra una
#: forma que el emisor no usa.
REGIONES_DE_DESARROLLO: Dict[str, Tuple[str, ...]] = {
    "OZAMA": ("DISTRITO NACIONAL", "SANTO DOMINGO"),
    "CIBAO NORTE": ("SANTIAGO", "PUERTO PLATA", "ESPAILLAT"),
    "CIBAO SUR": ("LA VEGA", "MONSEÑOR NOUEL", "SANCHEZ RAMIREZ"),
    "CIBAO NORDESTE": ("DUARTE", "HERMANAS MIRABAL", "MARIA TRINIDAD SANCHEZ", "SAMANA"),
    "CIBAO NOROESTE": ("VALVERDE", "SANTIAGO RODRIGUEZ", "DAJABON", "MONTE CRISTI"),
    "VALDESIA": ("SAN CRISTOBAL", "AZUA", "PERAVIA", "SAN JOSE DE OCOA"),
    "ENRIQUILLO": ("BARAHONA", "BAHORUCO", "PEDERNALES", "INDEPENDENCIA"),
    "EL VALLE": ("SAN JUAN", "ELIAS PIÑA"),
    "YUMA": ("LA ROMANA", "LA ALTAGRACIA", "EL SEIBO"),
    "HIGUAMO": ("SAN PEDRO DE MACORIS", "HATO MAYOR", "MONTE PLATA"),
}

#: Cómo las cuatro grandes agregan a las diez. Es la agregación que declara el diseño
#: muestral de la ENCFT y la que el cubo de la SIB reproduce.
DOMINIOS = {
    "ozama": ("OZAMA",),
    "norte": ("CIBAO NORTE", "CIBAO SUR", "CIBAO NORDESTE", "CIBAO NOROESTE"),
    "sur": ("VALDESIA", "ENRIQUILLO", "EL VALLE"),
    "este": ("YUMA", "HIGUAMO"),
}

#: El nombre con que la SIB rotula cada dominio en el cubo de crédito. Se declara en vez de
#: derivarse del texto: «Región Metropolitana» y «ozama» no se parecen, y adivinar el puente
#: por similitud es exactamente lo que este archivo existe para no hacer.
DOMINIO_POR_REGION_SIB = {
    "Región Metropolitana": "ozama",
    "Región Norte": "norte",
    "Región Sur": "sur",
    "Región Este": "este",
}


def provincias_del_dominio(dominio: str) -> Tuple[str, ...]:
    """Las provincias de uno de los cuatro dominios."""
    return tuple(p for r in DOMINIOS.get(dominio, ()) for p in REGIONES_DE_DESARROLLO[r])


def dominio_de_la_provincia(provincia: str) -> str | None:
    """El dominio de una provincia, o ``None`` si no está en la regionalización.

    Devuelve ``None`` —y no un dominio por defecto— para «SIN PROVINCIA» y para cualquier
    rótulo que la fuente traiga y no esté declarado: asignarlo al azar le atribuiría a esa
    cartera las condiciones laborales de un territorio que no le corresponde."""
    objetivo = (provincia or "").strip().upper()
    for dominio in DOMINIOS:
        if objetivo in provincias_del_dominio(dominio):
            return dominio
    return None
