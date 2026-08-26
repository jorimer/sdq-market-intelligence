"""Un eje no puede descontar del gate lo que le convenga.

`coverage_efectiva` existe porque el gate de readiness hacía una sola pregunta —«¿qué
fracción de tu índice tiene dato real?»— y el eje de evaluación de leyes responde otra:
«¿cuántas de las metas que la LEY se fijó estamos midiendo?». Con la primera lectura, cuanto
peor redactada esté la norma menos «listo» parece el producto, y el techo real del eje cae
bajo el umbral de publicación.

La corrección es correcta y es peligrosa: cualquier eje podría sacar del denominador lo que
no quiere medir. Estos tests son la cerradura. **Se aplican a TODOS los productos
registrados**, no al de leyes, porque el defecto que este repositorio paga una y otra vez es
el guard que existe en un motor y falta en el otro.
"""
import pytest

from shared.products.contract import DataHealth
from shared.products.readiness import COVERAGE_INSTRUMENT, _cobertura_que_puntua
from shared.products.registry import get_product, registered_sectors


@pytest.fixture(scope="module")
def ejes():
    """Los 16 ejes registrados con sus señales de datos.

    **Con sesión de base y esquema completo, a propósito.** Sin ella el barrido alcanzaba 2
    de 16 —los otros catorce levantaban `RuntimeError` al pedir la sesión— y el test pasaba
    igual, verde y ciego sobre el 87% de la plataforma. Un barrido que no encuentra nada es
    indistinguible de un barrido que no encuentra defectos.
    """
    import app.main  # noqa: F401 — importarlo es lo que REGISTRA los ejes
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from shared.database.base import Base

    motor = create_engine("sqlite://", connect_args={"check_same_thread": False},
                          poolclass=StaticPool)
    Base.metadata.create_all(motor)
    db = sessionmaker(bind=motor)()
    try:
        out = []
        for key in sorted(registered_sectors()):
            producto = get_product(key, db)
            if producto is not None:
                out.append((key, producto.data_signals()))
        yield out
    finally:
        db.close()


def test_el_barrido_ALCANZA_todos_los_ejes_y_al_menos_uno_descuenta(ejes):
    """El test del test. Si el barrido dejara de ver los ejes, los cuatro de abajo pasarían
    sin haber mirado nada — y el de leyes es hoy el único que descuenta, así que si se cae
    del barrido la cerradura queda abierta sobre el único que la necesita."""
    claves = [k for k, _ in ejes]
    assert len(claves) >= 16, f"el barrido solo alcanza {len(claves)} ejes: {claves}"
    descuentan = [k for k, d in ejes if getattr(d, "coverage_efectiva", None) is not None]
    assert descuentan, "ningún eje descuenta: los guards de abajo no probarían nada"
    assert "law" in descuentan


class TestElDescuentoExigeSuLINAJE:
    def test_sin_desglose_completo_el_gate_usa_la_CRUDA(self):
        """Una cobertura mejorada sin linaje es un descuento silencioso. El gate la ignora."""
        sin_desglose = DataHealth(coverage=0.5, coverage_kind=COVERAGE_INSTRUMENT,
                                  coverage_efectiva=0.9)
        assert _cobertura_que_puntua(sin_desglose)[0] == pytest.approx(0.5)

    def test_un_indice_normal_NO_puede_descontar_aunque_declare_la_cifra(self):
        """El descuento es del `coverage_kind`, no de quien lo pida. Un índice que declarara
        `coverage_efectiva` sin declararse instrumento seguiría puntuando por la cruda."""
        indice = DataHealth(coverage=0.4, coverage_efectiva=0.95, universo=100,
                            medidas=40, imposibles_por_el_instrumento=60)
        assert _cobertura_que_puntua(indice)[0] == pytest.approx(0.4)

    def test_con_el_desglose_completo_puntua_la_EFECTIVA_y_el_linaje_dice_las_DOS(self):
        d = DataHealth(coverage=0.46, coverage_kind=COVERAGE_INSTRUMENT,
                       coverage_efectiva=0.836, universo=90, medidas=46,
                       imposibles_por_el_instrumento=35)
        valor, linaje = _cobertura_que_puntua(d)
        assert valor == pytest.approx(0.836)
        assert "46 de 55" in linaje                 # lo medible
        assert "35 de 90" in linaje                 # lo excluido, nombrado
        assert "cruda=0.46" in linaje               # y la cifra que no desaparece

    def test_cero_imposibles_no_activa_el_camino(self):
        """Sin nada que descontar, descontar sería una operación nula que igual oscurece."""
        d = DataHealth(coverage=0.7, coverage_kind=COVERAGE_INSTRUMENT,
                       coverage_efectiva=0.7, universo=90, medidas=63,
                       imposibles_por_el_instrumento=0)
        assert _cobertura_que_puntua(d)[1] == ""


class TestTodosLosEjesRegistrados:
    def test_quien_descuenta_declara_el_desglose_ENTERO(self, ejes):
        for key, d in ejes:
            if getattr(d, "coverage_efectiva", None) is None:
                continue
            faltan = [c for c in ("universo", "medidas", "imposibles_por_el_instrumento")
                      if getattr(d, c, None) is None]
            assert not faltan, f"«{key}» descuenta del gate sin declarar {faltan}"
            assert d.coverage_kind == COVERAGE_INSTRUMENT, (
                f"«{key}» descuenta sin declararse cobertura de instrumento")

    def test_la_cifra_descontada_CUADRA_con_su_propio_desglose(self, ejes):
        """No basta con declarar los números: tienen que ser los que producen la cifra."""
        for key, d in ejes:
            if getattr(d, "coverage_efectiva", None) is None:
                continue
            medible = d.universo - d.imposibles_por_el_instrumento    # type: ignore[operator]
            assert medible > 0, f"«{key}» declara que NADA de su universo es medible"
            assert d.coverage_efectiva == pytest.approx(d.medidas / medible), (
                f"«{key}»: la cobertura efectiva no sale de su desglose")

    def test_lo_descontado_NUNCA_supera_al_universo_ni_come_lo_medido(self, ejes):
        for key, d in ejes:
            if getattr(d, "imposibles_por_el_instrumento", None) is None:
                continue
            assert d.imposibles_por_el_instrumento + d.medidas <= d.universo, (  # type: ignore[operator]
                f"«{key}» descuenta unidades que además cuenta como medidas")

    def test_el_default_de_TODO_eje_es_la_lectura_de_indice(self):
        """Un eje nuevo no hereda el descuento por accidente: tiene que pedirlo."""
        assert DataHealth(coverage=0.0).coverage_kind != COVERAGE_INSTRUMENT
        assert DataHealth(coverage=0.0).coverage_efectiva is None
