"""El canal que lleva una relación invertida desde el motor hasta quien decide publicar.

Hasta ahora el hallazgo moría en el motor: se escribía una línea de log y el informe se
entregaba igual. Así salió publicada la §7 de un Deep Dive de banca, afirmando que la
capitalización contable «supera» al promedio de su grupo estando por debajo — contradiciendo a
la §2 y a la §10 del MISMO documento.

La marca no puede viajar por el valor de retorno (`SectorProduct.narratives` devuelve
`Dict[str, str]`), y el motor no puede decidir la política porque es transversal y no sabe si
está sirviendo un premium o un Pulse. De ahí el acumulador.
"""
import asyncio

from shared.narrative.relaciones_pendientes import acumulando, registrar


def test_lo_registrado_llega_al_que_publica():
    with acumulando() as caja:
        registrar("comparative", ["patrimonio_activos: dice 'por encima', es 'por debajo'"])
    assert list(caja) == ["comparative"] and len(caja["comparative"]) == 1


def test_varias_secciones_se_acumulan_por_separado():
    with acumulando() as caja:
        registrar("comparative", ["a"])
        registrar("risk_assessment", ["b", "c"])
        registrar("comparative", ["d"])
    assert caja == {"comparative": ["a", "d"], "risk_assessment": ["b", "c"]}


def test_FUERA_del_acumulador_no_hace_nada():
    """Un job de fondo o un test que llame al motor sin abrir el acumulador no debe dejar
    basura en un global."""
    registrar("comparative", ["x"])  # no lanza
    with acumulando() as caja:
        pass
    assert caja == {}


def test_no_se_filtra_a_la_generacion_siguiente():
    with acumulando() as primera:
        registrar("comparative", ["a"])
    with acumulando() as segunda:
        pass
    assert primera and segunda == {}


def test_dos_generaciones_CONCURRENTES_no_se_mezclan():
    """El riesgo real del mecanismo. Cada tarea corre en su propio contexto; si se mezclaran,
    un informe se vetaría por el defecto de otro."""
    async def genera(nombre, hallazgo):
        with acumulando() as caja:
            registrar(nombre, [hallazgo])
            await asyncio.sleep(0)          # cede el control a la otra tarea
            registrar(nombre, [hallazgo + "-2"])
            return dict(caja)

    async def ambas():
        return await asyncio.gather(genera("uno", "A"), genera("dos", "B"))

    a, b = asyncio.run(ambas())
    assert a == {"uno": ["A", "A-2"]}, a
    assert b == {"dos": ["B", "B-2"]}, b


def test_registrar_nunca_lanza():
    """Registrar un hallazgo jamás puede tumbar una generación que salió bien."""
    with acumulando():
        registrar("x", [])
        registrar("x", None)  # type: ignore[arg-type]
