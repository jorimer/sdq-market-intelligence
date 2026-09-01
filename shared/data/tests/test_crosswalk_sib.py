"""La letra CIIU del cubo de crédito de la SIB, dentro del crosswalk sectorial.

Es la única fuente del mapa que trae CRÉDITO —cuánto se le presta a un sector, a qué tasa,
con qué mora—, y era la única que faltaba. Fase 2 del plan de enriquecimiento sectorial.

Las 19 etiquetas de abajo NO están transcritas de un informe: son los valores distintos que
la fuente emitió en los NUEVE cortes persistidos (2024-03 a 2026-03), leídos de producción el
2026-08-31. Las 19 aparecen en los nueve, así que el catálogo es estable.

Se fijan acá para que la tabla DECLARADA no se desincronice de lo medido: si alguien edita
una y no la otra, el test lo dice. Lo que este archivo NO puede detectar es que la SIB
renombre un sector mañana — eso se descubre en producción, y por eso `map_sib_label` cae a
la letra inicial: una etiqueta reescrita sigue resolviendo, que es lo que evita que media
cartera desaparezca del agregado por un cambio cosmético de la fuente. Se comprobó por
mutación: renombrar «H - ALOJAMIENTO…» a «H - HOTELES Y RESTAURANTES» sigue resolviendo a H.
"""
import pytest

from shared.data.bcrd_sectors import sector_catalog
from shared.data.sector_crosswalk import (SIB_KEYS, SIB_SECTORS, map_sib_label,
                                          sib_coverage, sib_members)

#: Medidas en producción el 2026-08-31 sobre los 9 cortes con dato.
ETIQUETAS_REALES = [
    "A - AGRICULTURA, GANADERÍA, CAZA Y SILVICULTURA",
    "B - PESCA",
    "C - EXPLOTACIÓN DE MINAS Y CANTERAS",
    "D - INDUSTRIA MANUFACTURERA",
    "E - SUMINISTRO DE ELECTRICIDAD, GAS, VAPOR Y AIRE ACONDICIONADO",
    "F - CONSTRUCCIÓN",
    "G - COMERCIO AL POR MAYOR Y AL POR MENOR; REPARACIÓN DE LOS VEHÍCULOS DE MOTOR Y DE LAS "
    "MOTOCICLETAS",
    "H - ALOJAMIENTO Y SERVICIOS DE COMIDA",
    "I - TRANSPORTE Y ALMACENAMIENTO",
    "J - ACTIVIDADES FINANCIERAS Y DE SEGURO",
    "K - ACTIVIDADES INMOBILIARIAS, ALQUILER Y ACTIVIDADES EMPRESARIALES",
    "L - ADMINISTRACIÓN PÚBLICA Y DEFENSA: PLANES DE SEGURIDAD SOCIAL DE AFILIACIÓN "
    "OBLIGATORIA",
    "M - ENSEÑANZA",
    "N - SERVICIOS SOCIALES Y RELACIONADOS CON LA SALUD HUMANA",
    "O - Otras actividades de servicios comunitarios, sociales y personales",
    "P - ACTIVIDADES DE LOS HOGARES EN CALIDAD DE EMPLEADORES, ACTIVIDADES INDIFERENCIADAS "
    "DE PRODUCCIÓN DE BIENES Y SERVICIOS DE LOS HOGARES PARA USO PROPIO",
    "Q - ACTIVIDADES DE ORGANIZACIONES Y ÓRGANOS EXTRATERRITORIALES",
    "Y - CONSUMO DE BIENES Y SERVICIOS",
    "Z - COMPRA Y REMODELACIÓN DE VIVIENDAS",
]


class TestElMapaResuelveLoQueLaFuenteEMITE:

    def test_el_barrido_no_esta_vacio(self):
        """Un `@parametrize` sobre una lista vacía sale SKIPPED, no FAILED."""
        assert len(ETIQUETAS_REALES) == 19

    @pytest.mark.parametrize("etiqueta", ETIQUETAS_REALES)
    def test_cada_etiqueta_real_resuelve_a_su_letra(self, etiqueta):
        letra = map_sib_label(etiqueta)
        assert letra == etiqueta[0], (
            f"«{etiqueta[:40]}…» no resuelve: esa letra caería fuera del agregado en "
            "silencio, y el denominador quedaría mal sin que nada falle")

    def test_las_etiquetas_DECLARADAS_son_las_medidas(self):
        """El anti-deriva de la tabla contra la medición. No lo cubre el test de resolución:
        `map_sib_label` cae a la letra inicial, así que una etiqueta reescrita sigue
        resolviendo y ese test pasaría igual — comprobado por mutación."""
        declaradas = {s.label for s in SIB_SECTORS}
        medidas = set(ETIQUETAS_REALES)
        assert declaradas == medidas, (
            f"la tabla declarada se separó de lo que la fuente emite.\n"
            f"  solo declaradas: {sorted(declaradas - medidas)}\n"
            f"  solo medidas:    {sorted(medidas - declaradas)}")

    def test_la_letra_sola_RESUELVE_aunque_cambie_la_etiqueta(self):
        """La resiliencia es deliberada: si la SIB reescribe un rótulo, la letra sigue
        mandando y esa cartera no desaparece del agregado."""
        assert map_sib_label("H - HOTELES Y RESTAURANTES") == "H"
        assert map_sib_label("F") == "F"

    def test_las_19_letras_estan_declaradas_y_sin_repetir(self):
        assert len(SIB_KEYS) == len(set(SIB_KEYS)) == 19
        assert {e[0] for e in ETIQUETAS_REALES} == set(SIB_KEYS)

    def test_una_etiqueta_DESCONOCIDA_no_se_atribuye_al_azar(self):
        """El contra-caso. `None` es información: la SIB amplió su marco y el consumidor
        tiene que dejar esa letra fuera, no repartirla."""
        assert map_sib_label("W - SECTOR QUE LA SIB TODAVÍA NO EMITE") is None
        assert map_sib_label("") is None
        assert map_sib_label(None) is None


class TestLoQueNOesUnSector:
    """Casi la mitad del crédito dominicano no va a un sector productivo."""

    @pytest.mark.parametrize("letra", ["Y", "Z", "P", "Q"])
    def test_no_alimentan_ningun_slug(self, letra):
        assert sib_members(letra) == [], (
            f"la letra {letra} se repartió entre sectores: eso es fabricar")

    def test_Y_y_Z_estan_declaradas_como_destino_de_hogares(self):
        por_letra = {s.key: s for s in SIB_SECTORS}
        for letra in ("Y", "Z"):
            assert por_letra[letra].kind == "no_sectorial"
            assert "hogares" in (por_letra[letra].note or "").lower()

    def test_la_cobertura_las_lista_aparte(self):
        assert sorted(sib_coverage()["no_sectorial"]) == ["P", "Q", "Y", "Z"]


class TestLaCoberturaEsPARCIALyLoDICE:

    def test_comunicaciones_es_la_unica_brecha_y_esta_declarada(self):
        """La J de la SIB es financiera, no «información y comunicaciones»: su marco no
        sigue la revisión 4 en ese punto. Es el único de los 17 sin crédito atribuible."""
        cov = sib_coverage()
        assert cov["uncovered"] == ["comunicaciones"]
        assert cov["n_slugs_covered"] == 16

    def test_cubierto_mas_brecha_es_el_catalogo_COMPLETO(self):
        """La prueba negativa: sin esto, un slug podría desaparecer de las dos listas."""
        cov = sib_coverage()
        todos = {slug for slug, _n in sector_catalog()}
        assert set(cov["covered"]) | set(cov["uncovered"]) == todos
        assert len(todos) == 17

    def test_ningun_slug_esta_en_las_DOS_listas(self):
        cov = sib_coverage()
        assert not (set(cov["covered"]) & set(cov["uncovered"]))


class TestLosBundlesYlosParciales:

    def test_D_no_separa_zonas_francas(self):
        assert sorted(sib_members("D")) == ["manufactura_local", "zonas_francas"]

    def test_K_agrupa_inmobiliario_con_servicios_profesionales(self):
        assert sorted(sib_members("K")) == ["inmobiliario", "servicios_profesionales"]

    def test_A_y_B_comparten_agropecuario(self):
        """La SIB separa agricultura de pesca; el marco BCRD no."""
        assert sib_members("A") == sib_members("B") == ["agropecuario"]

    @pytest.mark.parametrize("letra", ["A", "B", "D", "E", "K"])
    def test_todo_bundle_o_parcial_DECLARA_su_motivo(self, letra):
        """Un agregado sin nota se lee como un 1:1 y alguien lo cita como tal."""
        s = {x.key: x for x in SIB_SECTORS}[letra]
        assert s.kind in ("bundle", "partial")
        assert s.note and len(s.note) > 30, f"{letra} no dice por qué agrupa"

    def test_los_directos_NO_llevan_nota(self):
        """Contra-caso: si todo llevara nota, el test de arriba pasaría sin significar nada."""
        directos = [s for s in SIB_SECTORS if s.kind == "direct"]
        assert len(directos) == 10
        assert all(s.note is None and len(s.members) == 1 for s in directos)
