"""El informe entrega lo que un informe de valuación tiene que entregar.

**Cuatro defectos que este test fija, y los cuatro estaban en producción:**

1. **La portada no nombraba a la entidad.** Decía «SDQ Valuación de Entidades» y nada más.
   Un informe de valuación cuya tapa no nombra al sujeto valuado no se puede archivar ni
   citar.
2. **Dos secciones de un informe REAL se servían con la prosa de la MUESTRA.** El informe de
   un banco real terminaba diciendo «_Cifras ilustrativas de una entidad ficticia._» y
   publicando `Ke = Rf + β × ERP + CRP` — con prima de riesgo país, que este modelo NO tiene
   y cuyo docstring explica por qué no la tiene.
3. **El titular y las tablas no se renderizaban nunca.** El render leía `p["spread_pp"]` y
   `p["valor_rango"]` PLANAS y el payload las trae anidadas bajo `spread` y `valor`. El
   `.get` devolvía `None`, el bloque se saltaba, y nada fallaba.
4. **El tipo de entidad se perdía al pasar por el payload**, así que el informe decía
   «entidad de intermediación» genérica y la metodología mostraba una persistencia de 0,0.

Los cuatro comparten forma: **nada falla**. Un stub que devuelve vacío, una clave que no
existe, un texto de muestra que se sirve como real — ninguno rompe un test de tipos ni una
aserción numérica. Se ven leyendo el PDF.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.auth.models  # noqa: F401
from modules.banking_score.models.models import Bank, BankingData, BankType, DataSource
from modules.macro_monitor.models.models import MacroSeries
from modules.valuation.engine import crecimiento as cr
from modules.valuation.engine.cost_of_capital import SERIE_RF
from modules.valuation.products import (
    SECCION_ANTECEDENTES, SECCION_FINANCIERO, SECCION_FUENTES, SECCION_LIMITACIONES,
    SECCION_METODOLOGIA, SECCION_PROPOSITO, SECCION_RESUMEN, ValuationProduct)
from modules.valuation.service import a_payload, valuar_entidad
from shared.database.base import Base
from shared.products.tiers import ProductTier

CURVA = [("2025-01", 11.96), ("2025-04", 9.71), ("2025-07", 9.61), ("2025-10", 9.93),
         ("2026-01", 9.94), ("2026-03", 9.61), ("2026-05", 10.02), ("2026-07", 9.78)]


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    # Dos asociaciones, para que la POSICIÓN dentro del tipo se pueda computar.
    for i, (ident, nombre, patr) in enumerate((
            ("aap1", "Asociación Grande", 30_000_000_000.0),
            ("aap2", "Asociación Chica", 10_000_000_000.0))):
        s.add(Bank(id=ident, name=nombre, bank_type=BankType.aap))
        for j, anio in enumerate((2022, 2023, 2024, 2025)):
            s.add(BankingData(bank_id=ident, period_end=date(anio, 12, 31),
                              patrimonio_tecnico=patr * (1.05 ** j),
                              utilidad_neta=patr * 0.10, source=DataSource.sib_api))
    for p, v in CURVA:
        s.add(MacroSeries(series_code=SERIE_RF, period=p, value=v))
    for i in range(29):
        s.add(MacroSeries(series_code=cr.SERIE_PIB_NOMINAL,
                          period=f"{2019 + i // 4}-Q{i % 4 + 1}", value=9.03))
    s.commit()
    yield s
    s.close()


def _narrativas(db, tier=ProductTier.deep_dive):
    import asyncio
    prod = ValuationProduct(db)
    snap = prod.snapshot(tier, "2025-12-31", scope="aap1")
    return prod, snap, asyncio.run(prod.narratives(tier, snap))


def test_el_deep_dive_trae_TODAS_las_secciones_de_un_informe_de_valuacion(db):
    _prod, _snap, narr = _narrativas(db)
    for sec in (SECCION_RESUMEN, SECCION_PROPOSITO, SECCION_ANTECEDENTES, SECCION_FINANCIERO,
                SECCION_METODOLOGIA, SECCION_LIMITACIONES, SECCION_FUENTES):
        assert sec in narr and len(narr[sec]) > 200, f"falta o está vacía: {sec}"


def test_NINGUNA_seccion_de_un_informe_real_sale_de_la_MUESTRA(db):
    """El defecto más caro de los cuatro: el informe de un banco real decía que sus cifras
    eran de una entidad ficticia, y publicaba una fórmula de Ke que el modelo no usa."""
    _prod, _snap, narr = _narrativas(db)
    todo = " ".join(narr.values())
    assert "ficticia" not in todo.lower(), (
        "una sección real se está sirviendo con la prosa de la muestra")
    assert "ilustrativas" not in todo.lower()
    assert "CRP" not in todo, (
        "el informe publica una fórmula de Ke con prima de riesgo país, y este modelo tiene "
        "TRES términos — sumarla contaría el riesgo soberano dos veces")
    # Y la prueba POSITIVA, que es la que tiene dientes: las limitaciones de la muestra son
    # un texto fijo, así que no pueden citar el período ni el porcentaje de rúbrica de ESTA
    # entidad. Buscar solo palabras prohibidas dejaba pasar la versión de muestra que no las
    # usaba — se detectó corriendo la rotura, no leyendo el test.
    lim = narr[SECCION_LIMITACIONES]
    assert "2025-12-31" in lim, (
        "la sección de limitaciones no cita el período valuado: está saliendo de un texto "
        "fijo y no del dato")
    assert "%" in lim and "costo de capital no se observa" in lim


def test_el_TIPO_de_entidad_sobrevive_al_payload(db):
    """Se perdía en la ida y vuelta, y con él la persistencia y su evidencia."""
    lec = valuar_entidad(db, bank_id="aap1", nombre="Asociación Grande")
    payload = a_payload(lec)
    assert payload["tipo_de_entidad"] == "aap"
    assert payload["procedencia"]["persistencia"] == pytest.approx(0.358)
    _prod, _snap, narr = _narrativas(db)
    assert "asociación de ahorros y préstamos" in narr[SECCION_ANTECEDENTES].lower()
    assert "0.358" in narr[SECCION_METODOLOGIA]


def test_la_concordancia_de_GENERO_es_correcta_en_los_cuatro_tipos():
    """«un asociación» y «asociación supervisado» son errores que ningún test numérico ve."""
    from modules.valuation import narrativa as n
    from modules.valuation.service import Lectura
    for tipo, esperado in (("banca_multiple", "un banco múltiple supervisado"),
                           ("aap", "una asociación de ahorros y préstamos supervisada"),
                           ("corporacion_credito", "una corporación de crédito supervisada"),
                           ("", "una entidad de intermediación supervisada")):
        lec = Lectura(entidad="X", periodo="2025-12-31", moneda="DOP",
                      roe_proyectado_pct=10.0, ke_bajo_pct=9.0, ke_alto_pct=12.0,
                      spread_bajo_pp=-2.0, spread_alto_pp=1.0, cambia_de_signo=True,
                      patrimonio_libro=100.0, valor_bajo=90.0, valor_alto=120.0,
                      pb_bajo=0.9, pb_alto=1.2, fraccion_de_rubrica=0.37, advertencias=(),
                      tipo_de_entidad=tipo)
        assert esperado in n.antecedentes(lec), f"{tipo}: concordancia mal"


def test_la_POSICION_en_su_tipo_se_COMPUTA_sobre_el_padron_completo(db):
    """Una posición de mercado afirmada sin computarla es una opinión."""
    _prod, _snap, narr = _narrativas(db)
    ant = narr[SECCION_ANTECEDENTES]
    assert "puesto 1 de 2" in ant, f"no computó la posición: {ant[:300]}"
    assert "75.0 %" in ant, "no computó la cuota del patrimonio del grupo"


def test_el_analisis_financiero_NO_habla_de_EBITDA(db):
    """El estándar genérico lo pide y en una entidad financiera no mide nada. Que el informe
    lo diga es parte del método, no una omisión."""
    _prod, _snap, narr = _narrativas(db)
    fin = narr[SECCION_FINANCIERO]
    assert "EBITDA" in fin and "no mide nada" in fin, (
        "el informe no explica por qué no usa EBITDA")
    assert "| Cierre | ROE |" in fin, "falta la serie histórica de ROE"


def test_el_render_pone_la_ENTIDAD_en_la_portada_y_arma_las_tablas(db):
    """El titular y las tablas leían claves PLANAS que el payload no tiene."""
    import asyncio
    prod, snap, narr = _narrativas(db)
    p = snap.payload
    assert (p.get("spread") or {}).get("spread_pp"), "el payload cambió de forma"
    ruta = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr, output_dir="/tmp"))
    assert ruta.endswith(".pdf")
    # Se comprueba en el PDF PRODUCIDO, no en el snapshot. Afirmar que el snapshot trae el
    # nombre no dice nada sobre la portada: el render podía —y podía de verdad— tirarlo.
    from pypdf import PdfReader
    texto = "\n".join((pg.extract_text() or "") for pg in PdfReader(ruta).pages[:1])
    assert "Asociación Grande" in texto, (
        "la PORTADA no nombra a la entidad valuada; decía solo «SDQ Valuación de Entidades»")
    completo = "\n".join((pg.extract_text() or "") for pg in PdfReader(ruta).pages)
    assert "Conclusión de valor" in completo and "Costo de capital y retorno" in completo, (
        "las tablas no se renderizaron: el render leía claves planas que el payload no tiene")
    assert "ROE" in completo and "Ke" in completo
