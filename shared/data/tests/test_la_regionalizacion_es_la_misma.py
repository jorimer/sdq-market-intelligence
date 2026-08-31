"""Las dos nomenclaturas hablan de lo mismo, y hay un test que lo comprueba.

**La pregunta.** El cubo de crédito de la SIB trae una región por provincia; la ENCFT publica
el mercado laboral por dominio geográfico. ¿Se pueden cruzar? Los nombres se parecen —
«Región Norte» y «Región Norte o Cibao»— pero parecerse fue exactamente lo que falló con
`tasa_de_inflacion_c5`, donde cinco columnas se llamaban igual y eran de quintiles distintos.

**Lo que se comprobó, y en qué orden.** La primera búsqueda no alcanzó: la hoja de la ENCFT
dice «según macro regiones», y el Decreto 710-04 define TRES macrorregiones (Cibao, Suroeste,
Sureste) con Ozama adentro de Sureste — o sea que el término estaba usado en sentido laxo y
habría servido de ancla FALSA. El dueño insistió en buscar mejor, y el catálogo IHSN del
diseño muestral de la ENCFT trae el ancla real: sus dominios de estimación se redujeron a
«las cuatro grandes regiones geográficas: Gran Santo Domingo u Ozama, Norte o Cibao, Sur y
Este», construidas sobre las 10 Regiones de Desarrollo del mismo decreto.

Con esa composición declarada, la partición que el cubo de la SIB publica en producción
coincide PROVINCIA POR PROVINCIA en las 32.

**Qué protege este archivo.** Que la composición declarada siga siendo la del decreto, y que
el cruce se apague si alguna vez deja de coincidir — en vez de empezar a atribuirle a una
provincia las condiciones laborales de otra sin que nadie se entere.
"""

import pytest

from shared.data.regiones_rd import (
    DOMINIO_POR_REGION_SIB, DOMINIOS, REGIONES_DE_DESARROLLO,
    dominio_de_la_provincia, provincias_del_dominio,
)

#: La partición OBSERVADA en producción el 2026-08-31, tal como la publica el cubo de la SIB.
#: Se fija como constante para que el test sea un contraste y no una tautología: si la SIB
#: reagrupa, hay que actualizar esto A CONCIENCIA y revisar el cruce.
SIB_OBSERVADA = {
    "Región Metropolitana": ("DISTRITO NACIONAL", "SANTO DOMINGO"),
    "Región Norte": ("DAJABON", "DUARTE", "ESPAILLAT", "HERMANAS MIRABAL", "LA VEGA",
                     "MARIA TRINIDAD SANCHEZ", "MONSEÑOR NOUEL", "MONTE CRISTI",
                     "PUERTO PLATA", "SAMANA", "SANCHEZ RAMIREZ", "SANTIAGO",
                     "SANTIAGO RODRIGUEZ", "VALVERDE"),
    "Región Sur": ("AZUA", "BAHORUCO", "BARAHONA", "ELIAS PIÑA", "INDEPENDENCIA",
                   "PEDERNALES", "PERAVIA", "SAN CRISTOBAL", "SAN JOSE DE OCOA", "SAN JUAN"),
    "Región Este": ("EL SEIBO", "HATO MAYOR", "LA ALTAGRACIA", "LA ROMANA", "MONTE PLATA",
                    "SAN PEDRO DE MACORIS"),
}


def test_las_diez_regiones_cubren_las_32_unidades_del_pais():
    """31 provincias más el Distrito Nacional. Si falta una, alguna cartera queda sin
    dominio y su condición laboral no se puede afirmar."""
    todas = [p for ps in REGIONES_DE_DESARROLLO.values() for p in ps]
    assert len(todas) == 32
    assert len(set(todas)) == 32, "una provincia declarada en dos regiones"


def test_los_cuatro_dominios_agregan_las_diez_regiones_sin_dejar_ninguna():
    agregadas = [r for rs in DOMINIOS.values() for r in rs]
    assert sorted(agregadas) == sorted(REGIONES_DE_DESARROLLO), (
        "una Región de Desarrollo quedó fuera de los cuatro dominios")


@pytest.mark.parametrize("region_sib", sorted(SIB_OBSERVADA))
def test_la_particion_de_la_SIB_coincide_con_la_declarada(region_sib):
    """El contraste que sostiene todo el cruce."""
    dominio = DOMINIO_POR_REGION_SIB[region_sib]
    assert sorted(provincias_del_dominio(dominio)) == sorted(SIB_OBSERVADA[region_sib]), (
        f"«{region_sib}» ya no coincide con el dominio «{dominio}»: el cruce entre crédito "
        f"y mercado laboral estaría atribuyendo a una provincia el dato de otra")


def test_cada_region_de_la_SIB_tiene_su_dominio_declarado():
    """«Región Metropolitana» y «ozama» no se parecen: el puente se declara, no se adivina."""
    assert sorted(DOMINIO_POR_REGION_SIB.values()) == sorted(DOMINIOS)


@pytest.mark.parametrize("provincia,dominio", [
    ("DISTRITO NACIONAL", "ozama"), ("SANTIAGO", "norte"),
    ("SAN CRISTOBAL", "sur"), ("LA ALTAGRACIA", "este"),
    ("MONTE PLATA", "este"),      # Higuamo: la que más se presta a confusión
])
def test_provincias_de_control(provincia, dominio):
    assert dominio_de_la_provincia(provincia) == dominio


@pytest.mark.parametrize("rotulo", ["SIN PROVINCIA", "", "MIAMI", None])
def test_lo_que_no_esta_en_la_regionalizacion_NO_recibe_un_dominio(rotulo):
    """Asignarle uno le atribuiría condiciones laborales de un territorio que no le
    corresponde. `None` es la respuesta honesta y la que el cruce sabe declarar."""
    assert dominio_de_la_provincia(rotulo) is None


def test_NO_es_la_macrorregionalizacion_de_TRES():
    """El decreto agrupa las diez en TRES macrorregiones —Ozama va dentro de Sureste— y ni
    la SIB ni la ENCFT usan ésa. Dejarlo fijado evita que alguien «corrija» los cuatro
    dominios hacia los tres oficiales creyendo que arregla algo."""
    assert len(DOMINIOS) == 4
    assert "ozama" in DOMINIOS and "este" in DOMINIOS
    assert provincias_del_dominio("ozama") != provincias_del_dominio("este")
