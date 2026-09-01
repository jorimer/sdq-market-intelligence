"""Construcción recibe el financiamiento de su sector — fase 4 del plan sectorial.

El eje medía permisos, m², diversificación tipológica y amplitud geográfica: actividad
física, sin una sola señal de cómo se financia. Cuánto crédito recibe la construcción, a qué
tasa y con qué mora sale del cubo de la SIB y hasta ahora solo lo veía banca.

Lo que se protege es el SUJETO y la DIRECCIÓN, que son los dos modos en que este contexto se
publica mal: el modelo tiene cerca los permisos y los m², y una clave como `credito_pct` la
reatribuye al sujeto más próximo.
"""
from datetime import date

import pytest

from modules.construction_intel.ai_context import _financiamiento

_PERFIL = {
    "sector": "construccion",
    "credito_del_sistema": {
        "sector": "construccion", "corte": "2025-12-31",
        "deuda_del_sistema_al_sector": 161_000_000_000.0,
        "peso_del_sector_en_el_credito_del_pais_pct": 6.86,
        "entidades_que_le_prestan": 28,
        "mora_pct": 1.42, "mora_temprana_31_90_pct": 0.31,
        "tasa_promedio_ponderada_pct": 11.4,
        "cobertura_de_provision_sobre_vencida_pct": 210.0,
        "garantia_sobre_deuda_pct": 58.0, "credito_promedio": 4_100_000.0,
        "es_agregado": False, "el_agregado_incluye": None,
    },
    "costo_laboral": {"salario_promedio_cotizable_del_sector_dop_mes": 28_500.0,
                      "anio": "2025", "fuente": "TSS"},
}


class TestElSujetoViajaEnCadaClave:

    def test_ninguna_clave_de_cuota_queda_sin_poblacion(self):
        """`credito_pct` al lado de los permisos se lee como cuota de permisos."""
        c = _financiamiento(_PERFIL)["credito_del_sistema_al_sector_construccion"]
        for clave in c:
            if clave.endswith("_pct"):
                assert "construccion" in clave or "credito_del_pais" in clave, (
                    f"«{clave}» afirma una porción sin decir de qué población")

    def test_el_bloque_nombra_al_sector_desde_su_clave_raiz(self):
        out = _financiamiento(_PERFIL)
        assert "credito_del_sistema_al_sector_construccion" in out
        assert "costo_laboral_del_sector_construccion" in out

    def test_las_cifras_se_COPIAN_sin_recalcularse(self):
        c = _financiamiento(_PERFIL)["credito_del_sistema_al_sector_construccion"]
        assert c["mora_del_sector_construccion_pct"] == 1.42
        assert c["tasa_promedio_ponderada_al_sector_construccion_pct"] == 11.4
        assert c["peso_de_la_construccion_en_la_cartera_del_sistema_pct"] == 6.86


class TestCadaCapaTraeSuFECHA:

    def test_el_credito_trae_su_corte(self):
        """Es una capa de otro período que el índice: sin su corte, el modelo la fecha en el
        encabezado del informe."""
        c = _financiamiento(_PERFIL)["credito_del_sistema_al_sector_construccion"]
        assert c["corte_de_esta_capa"] == "2025-12-31"

    def test_el_salario_trae_su_anio(self):
        s = _financiamiento(_PERFIL)["costo_laboral_del_sector_construccion"]
        assert s["anio_de_esta_capa"] == "2025"


class TestLoQueNoHayNoSeMENCIONA:

    def test_sin_perfil_no_hay_claves(self):
        """Decisión del dueño (2026-08-31): lo que no se puede afirmar no se menciona. Sin
        clave, el modelo no tiene qué citar."""
        assert _financiamiento(None) == {}
        assert _financiamiento({}) == {}

    def test_con_solo_una_lectura_sale_esa_y_no_la_otra(self):
        solo_credito = {"credito_del_sistema": _PERFIL["credito_del_sistema"]}
        out = _financiamiento(solo_credito)
        assert "credito_del_sistema_al_sector_construccion" in out
        assert "costo_laboral_del_sector_construccion" not in out


class TestUnAgregadoSeDECLARAenElContexto:

    def test_si_la_cifra_es_de_un_agregado_el_modelo_se_entera(self):
        """Construcción es letra propia (F), así que hoy nunca es agregado — pero el bloque
        es genérico y el día que se reutilice para manufactura la `D` sí lo es. Sin este
        aviso, el modelo atribuiría la cifra del agregado al sector que nombra la clave."""
        perfil = {"credito_del_sistema": {**_PERFIL["credito_del_sistema"],
                                          "es_agregado": True,
                                          "el_agregado_incluye": ["a", "b"]}}
        c = _financiamiento(perfil)["credito_del_sistema_al_sector_construccion"]
        aviso = [k for k in c if "agregado" in k]
        assert aviso and c[aviso[0]] == ["a", "b"]

    def test_cuando_NO_es_agregado_no_se_ensucia_el_contexto(self):
        c = _financiamiento(_PERFIL)["credito_del_sistema_al_sector_construccion"]
        assert not [k for k in c if "agregado" in k]


def test_el_snapshot_pide_el_perfil_al_CIERRE_del_anio():
    """El período de este producto es anual y el cubo es trimestral: un año se lee con su
    diciembre. Con el corte de marzo el bloque describiría otro trimestre que el encabezado.

    Se lee la LLAMADA con `ast`, no el nombre en el texto: el comentario que explica el
    arreglo menciona «diciembre» y un test de texto se satisfaría con eso.
    """
    import ast
    import inspect

    from modules.construction_intel import products
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(products)))
              if isinstance(n, ast.FunctionDef) and n.name == "snapshot")
    llamadas = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "perfil_del_sector"]
    assert llamadas, "el snapshot dejó de pedir el perfil del sector"
    corte = llamadas[0].args[2]
    assert isinstance(corte, ast.Call) and getattr(corte.func, "id", "") == "date"
    mes, dia = corte.args[1], corte.args[2]
    assert (mes.value, dia.value) == (12, 31), (
        "el perfil se pide a un corte que no es el cierre del año")
