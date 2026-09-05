"""No se comparan niveles entre países salvo que vengan de EMFA.

**De dónde sale la regla, y por qué no es una cautela nuestra.** La propia SECMCA declara
por escrito, en la página de su Estadística del Sistema Bancario, que «estos indicadores no
están armonizados», y remite a EMFA para los que sí lo están. Si el organismo regional lo
dice de su propia región, nosotros no podemos afirmar lo contrario poniendo dos columnas al
lado.

**Por qué un test y no una regla de estilo.** La disciplina editorial de no hacer rankings no
sobrevive a la edición doce: el ranking es exactamente lo que más se comparte y alguien lo va
a pedir «solo por esta vez». Y una comparación inválida no se ve rota — se ve como una tabla
perfectamente ordenada en la que una columna mide otra cosa.

**Las dos capas.** `exigir_comparable` levanta ante la mezcla (fail-closed: en un ensamblado
automático «avisar» no es «proteger», el warning se pierde y el documento sale igual), y el
barrido de abajo exige que toda tabla multi-país del módulo pase por ahí — porque un guard
que existe y nadie llama es un comentario.
"""
import ast
import pathlib

import pytest

from modules.regional_banking.ai_context import (
    NORMAS_ARMONIZADAS, ComparacionNoArmonizada, contexto_armonizado, contexto_por_sistema,
    exigir_comparable,
)

RAIZ = pathlib.Path(__file__).resolve().parents[3]
MODULO = RAIZ / "modules" / "regional_banking"


class _Fila:
    """Lo mínimo que `exigir_comparable` mira de una fila."""

    def __init__(self, iso, norma, metric="solvencia", valor=1.0):
        self.iso_code, self.norma_contable, self.metric, self.value = iso, norma, metric, valor


class TestLaRegla:
    def test_rechaza_la_tabla_que_mezcla_normas(self):
        """El caso construido a propósito: Colombia (CUIF) al lado de una plaza de EMFA."""
        with pytest.raises(ComparacionNoArmonizada) as e:
            exigir_comparable([_Fila("COL", "CUIF Colombia (SFC)"),
                               _Fila("DOM", "EMFA armonizado")])
        assert "no están armonizadas" in str(e.value)

    def test_rechaza_dos_supervisores_nacionales_entre_si(self):
        """Ni siquiera dos normas nacionales distintas entre sí: cada una mide lo suyo."""
        with pytest.raises(ComparacionNoArmonizada):
            exigir_comparable([_Fila("COL", "CUIF Colombia (SFC)"),
                               _Fila("BRA", "Res. CMN 4966")])

    def test_acepta_lo_armonizado(self):
        filas = [_Fila("DOM", "EMFA armonizado"), _Fila("CRI", "EMFA armonizado")]
        assert exigir_comparable(filas) == filas

    def test_un_solo_pais_no_compara_con_nadie(self):
        """La regla es sobre COMPARAR: una serie de un país no compara aunque no esté
        armonizada, y bloquearla sería impedir narrar la trayectoria, que es §2."""
        filas = [_Fila("COL", "CUIF Colombia (SFC)"), _Fila("COL", "CUIF Colombia (SFC)")]
        assert exigir_comparable(filas) == filas

    def test_la_lista_de_normas_armonizadas_es_cerrada(self):
        """Una fuente nueva no se vuelve comparable por parecerlo: entra acá o no compara."""
        assert NORMAS_ARMONIZADAS == frozenset({"EMFA armonizado"})


def _funciones_que_arman_tablas():
    """`(archivo, función)` de todo lo que produce una tabla que cruza países.

    Se detecta por la marca del propio módulo: una función que CONSTRUYE un dict con la
    clave `tabla_comparable` está armando una comparación entre países.

    Construir, no mencionar: `contexto_o_nada` LEE esa clave para decidir si hay sección, y
    marcarla sería un falso positivo. Un detector que no puede explicar por qué un caso
    bueno queda limpio todavía no es un detector.
    """
    fuera = []
    for path in sorted(MODULO.rglob("*.py")):
        if "tests" in path.parts:
            continue
        arbol = ast.parse(path.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            construye = any(
                isinstance(n, ast.Dict)
                and any(isinstance(k, ast.Constant) and k.value == "tabla_comparable"
                        for k in n.keys if k is not None)
                for n in ast.walk(nodo))
            if construye:
                llama = any(
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "exigir_comparable" for n in ast.walk(nodo))
                fuera.append((path.relative_to(RAIZ).as_posix(), nodo.name, llama))
    return fuera


def test_el_barrido_ENCUENTRA_tablas():
    """Un barrido que no encuentra nada pasa en verde sin haber mirado nada."""
    assert _funciones_que_arman_tablas(), (
        "el barrido no encontró ninguna tabla comparable en el módulo — la regla no "
        "protege nada")


@pytest.mark.parametrize("archivo,funcion,llama", _funciones_que_arman_tablas(),
                         ids=lambda v: str(v))
def test_toda_tabla_multipais_pasa_por_el_guard(archivo, funcion, llama):
    assert llama, (
        f"{archivo}::{funcion} arma una tabla que cruza países y NO llama a "
        f"`exigir_comparable`. Una comparación entre normas contables distintas no se ve "
        f"rota: se ve como una tabla ordenada donde una columna mide otra cosa.")


class TestContraElBoletinReal:
    """Y pasa contra el boletín de verdad, que es la otra mitad de la aceptación."""

    def test_la_seccion_por_sistema_no_arma_tabla_entre_paises(self, db_regional):
        contexto = contexto_por_sistema(db_regional)
        assert "tabla_comparable" not in contexto
        assert contexto["bloques_por_pais"], "sin países no hay nada que narrar"
        # Cada bloque declara su norma: el sujeto viaja con el número.
        for bloque in contexto["bloques_por_pais"]:
            assert bloque["norma_contable"]
            assert bloque["corte"]

    def test_la_seccion_armonizada_solo_trae_EMFA(self, db_regional):
        contexto = contexto_armonizado(db_regional)
        normas = {f["norma_contable"] for f in contexto["tabla_comparable"]}
        assert normas <= NORMAS_ARMONIZADAS
        assert all(f["comparable_entre_paises"] for f in contexto["tabla_comparable"])

    def test_el_credito_de_EMFA_no_entra_a_la_tabla_comparable(self, db_regional):
        """EMFA armoniza la metodología, no la UNIDAD: sus saldos vienen en moneda local y
        el cuadro de origen deja la unidad en blanco."""
        metricas = {f["metrica"].split("::")[0]
                    for f in contexto_armonizado(db_regional)["tabla_comparable"]}
        assert metricas and not any(m.startswith("credito") for m in metricas)
