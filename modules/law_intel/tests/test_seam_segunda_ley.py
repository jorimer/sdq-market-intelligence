"""LA PRUEBA DEL SEAM: una segunda ley no puede obligar a tocar el motor.

Meta RD 2036 se eligió por ser lo más distinto posible de la END: un decreto en vez de una
ley orgánica, UN indicador en vez de noventa, sin ejes temáticos y con una meta relativa
(«duplicar») en vez de un valor. Si el motor la sirve sin cambios, el seam funciona.

Estos tests son el criterio de aceptación declarado cuando se diseñó el módulo. No prueban
que Meta RD 2036 esté bien cargado — prueban que el motor no sabe de ninguna ley.
"""
import pytest

from modules.law_intel.bindings import cargar_bindings, cobertura
from modules.law_intel.obligaciones import cargar_obligaciones
from modules.law_intel.obligaciones import resumen as res_ob
from modules.law_intel.registro import cargar, expedientes
from modules.law_intel.scoring.accionabilidad import recomendaciones
from modules.law_intel.scoring.brecha import brechas
from modules.law_intel.scoring.coherencia_proceso import revisar
from modules.law_intel.scoring.semaforo import panel

SEGUNDA = "meta_rd_2036"


def test_hay_mas_de_un_expediente():
    """Con uno solo, el seam no está probado: está afirmado."""
    assert len(expedientes()) >= 2


def test_la_segunda_ley_carga():
    e = cargar(SEGUNDA)
    assert e.norma == "Decreto 337-24"
    assert len(e.numerados) == 1


@pytest.mark.parametrize("motor", ["cobertura", "semaforo", "brechas", "obligaciones",
                                   "recomendaciones", "coherencia"])
def test_todos_los_motores_la_sirven_sin_cambios(motor):
    e = cargar(SEGUNDA)
    bs = cargar_bindings(SEGUNDA)
    {
        "cobertura": lambda: cobertura(SEGUNDA),
        "semaforo": lambda: panel(e.numerados, bs, {}, "2025"),
        "brechas": lambda: brechas(e.numerados, bs),
        "obligaciones": lambda: res_ob(SEGUNDA),
        "recomendaciones": lambda: recomendaciones(brechas(e.numerados, bs),
                                                   cargar_obligaciones(SEGUNDA)),
        "coherencia": lambda: revisar(SEGUNDA, {i.id: i for i in e.indicadores}, "2025"),
    }[motor]()


def test_un_expediente_sin_obligaciones_ni_pactos_no_rompe():
    """Un decreto puede no tener registro de obligaciones ni instrumentos de proceso. La
    ausencia de un archivo opcional es un expediente más chico, no un error."""
    assert cargar_obligaciones(SEGUNDA) == []
    assert revisar(SEGUNDA, {}, "2025") == []


def test_una_meta_relativa_no_finge_ser_numerica(self=None):
    """«Duplicar el PIB real» es aritmética sobre una base que el decreto NO declara.
    Suponerla sería inventar el punto de partida contra el que se juzga todo lo demás."""
    i = cargar(SEGUNDA).numerados[0]
    assert i.escala == "redactada"
    assert not i.admite_delta
    assert i.base_valor is None


class TestElEjeLoDeclaraElExpediente:
    """El único supuesto de la END que se había filtrado fuera del expediente.

    La validación decía `le=4` —los cuatro ejes de la END— y un instrumento con cinco habría
    recibido un 422 por una consulta legítima.
    """

    def test_la_end_declara_cuatro(self):
        assert set(cargar("end_2030").meta["ejes"]) == {1, 2, 3, 4}

    def test_el_decreto_declara_uno(self):
        assert set(cargar(SEGUNDA).meta["ejes"]) == {1}

    def test_el_rotulo_dice_que_no_son_ejes_del_instrumento(self):
        """No se le inventa una taxonomía al decreto para que entre en la forma de la END."""
        assert "sin ejes" in cargar(SEGUNDA).meta["ejes"][1]
