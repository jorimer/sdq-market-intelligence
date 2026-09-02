"""La operación que cierra el hueco del desglose sectorial, de a un trimestre.

Por qué existe con esta forma. Un deploy de Railway reinicia el worker y mata la operación
en vuelo: el 2026-08-29 un backfill de 2h30 murió en el trimestre 14 de 22 y no dejó nada.
Una operación con cadencia tiene que ser corta, idempotente y reanudable, o cada despliegue
la rompe. Ésta procesa UN corte por corrida y recomputa la brecha contra la base en cada
pasada, así que una interrupción cuesta ocho minutos y la siguiente retoma donde quedó.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — registra users para las FK
from shared.database.base import Base
from modules.banking_score import operations as ops
from modules.banking_score.models.models import Bank, BankType, BankingData
from shared.reference.cartera_sectorial import CarteraSectorial


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    b = Bank(name="Banco Uno", bank_type=BankType.banca_multiple)
    s.add(b)
    s.flush()
    for pe in (date(2025, 3, 31), date(2025, 6, 30), date(2025, 9, 30)):
        s.add(BankingData(bank_id=b.id, period_end=pe))
    # Solo uno de los tres tiene el libro abierto por sector.
    s.add(CarteraSectorial(bank_id=b.id, period_end=date(2025, 6, 30),
                           sector="F - CONSTRUCCIÓN", provincia="SANTIAGO", deuda=100))
    s.commit()
    return s


@pytest.fixture()
def db_con_muchos_huecos():
    """Doce trimestres con datos bancarios y NINGUNO con desglose.

    Existe para ejercitar el TOPE de intentos, que la fixture chica no alcanza a tocar.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    b = Bank(name="Banco Dos", bank_type=BankType.banca_multiple)
    s.add(b)
    s.flush()
    for anio in (2023, 2024, 2025):
        for mes, dia in ((3, 31), (6, 30), (9, 30), (12, 31)):
            s.add(BankingData(bank_id=b.id, period_end=date(anio, mes, dia)))
    s.commit()
    return s


class TestLaBrechaSeCOMPUTA:
    def test_son_los_cortes_con_datos_y_SIN_desglose(self, db):
        assert ops.cortes_sin_desglose_sectorial(db) == [date(2025, 9, 30), date(2025, 3, 31)]

    def test_viene_del_mas_NUEVO_al_mas_viejo(self, db):
        """El corte reciente es el que se publica; el histórico puede esperar una corrida."""
        faltan = ops.cortes_sin_desglose_sectorial(db)
        assert faltan == sorted(faltan, reverse=True)

    def test_un_corte_que_se_completa_DESAPARECE_solo(self, db):
        """La brecha se recomputa contra la base, no contra una lista guardada: por eso la
        operación es idempotente y reanudable."""
        b = db.query(Bank).first()
        db.add(CarteraSectorial(bank_id=b.id, period_end=date(2025, 9, 30),
                                sector="G - COMERCIO", provincia="AZUA", deuda=50))
        db.commit()
        assert date(2025, 9, 30) not in ops.cortes_sin_desglose_sectorial(db)

    def test_sin_brecha_devuelve_lista_vacia_y_no_falla(self, db):
        for pe in (date(2025, 3, 31), date(2025, 9, 30)):
            db.add(CarteraSectorial(bank_id=db.query(Bank).first().id, period_end=pe,
                                    sector="X", provincia="Y", deuda=1))
        db.commit()
        assert ops.cortes_sin_desglose_sectorial(db) == []


class TestLaOperacionEsCortaYReanudable:
    def test_procesa_UN_corte_por_corrida_por_defecto(self, db, monkeypatch):
        """Si procesara todos, una corrida duraría 2h30 y el próximo deploy la mataría."""
        llamados = []
        monkeypatch.setattr(ops, "SessionLocal", lambda: db)
        monkeypatch.setattr("modules.banking_score.sib_sync.recompute_carteras_metrics",
                            lambda p, write_status=None: llamados.append(p) or {"rows_updated": 7})
        r = ops._run_sectorial_al_dia({}, None, lambda *_: None)
        assert len(llamados) == 1 and r["faltaban"] == 2 and r["quedan"] == 1

    def test_un_corte_sin_cubo_se_REPORTA_y_no_se_da_por_hecho(self, db, monkeypatch):
        """La SIB publica el cubo con retraso: «todavía no está» no es «ya se cargó»."""
        monkeypatch.setattr(ops, "SessionLocal", lambda: db)
        monkeypatch.setattr("modules.banking_score.sib_sync.recompute_carteras_metrics",
                            lambda p, write_status=None: {"rows_updated": 0})
        r = ops._run_sectorial_al_dia({}, None, lambda *_: None)
        assert r["procesados"][0]["sin_cubo"] is True

    def test_sin_nada_pendiente_lo_dice_en_vez_de_correr_en_vano(self, db, monkeypatch):
        monkeypatch.setattr(ops, "SessionLocal", lambda: db)
        monkeypatch.setattr(ops, "cortes_sin_desglose_sectorial", lambda _db: [])
        r = ops._run_sectorial_al_dia({}, None, lambda *_: None)
        assert r["faltaban"] == 0 and r["procesados"] == []


def test_tiene_cadencia_y_NO_exige_parametros():
    """Sin cadencia no se agenda; con parámetros obligatorios, `seed_default_schedules` la
    omite (ver `shared/operations/freshness.py`)."""
    from shared.operations import OPERATIONS
    op = OPERATIONS["cartera-sectorial-al-dia"]
    assert op.default_interval_hours > 0
    assert not op.needs_params


class TestLaColaNoSeAtora:
    """El defecto medido el 2026-09-01 en producción.

    La brecha viene del más nuevo al más viejo y la corrida tomaba `faltan[:1]` a secas. El
    cubo de crédito de la SB va un trimestre detrás de los estados financieros, así que la
    CABEZA de esa lista es casi siempre un corte que la fuente todavía no publicó: volvía con
    cero filas, seguía en la brecha, y a la semana siguiente se lo volvía a tomar. Todo lo
    que estuviera detrás no llegaba nunca.

    Medido: de 23 trimestres con datos bancarios, 21 tenían desglose y los dos que faltaban
    eran los EXTREMOS —2026-06-30, sin publicar, y 2020-12-31—. El segundo llevaba semanas
    detrás del primero sin que le llegara el turno.

    La cura no es procesar más: es contar el presupuesto en cortes que CARGARON, no en
    intentos. Un corte sin cubo vuelve casi enseguida y con cero filas; el costo real (~8
    minutos) está en la escritura.
    """

    @staticmethod
    def _con_cubo_solo_en(monkeypatch, db, periodos_con_cubo):
        """Sustituye la ingesta: devuelve filas solo para los períodos declarados."""
        intentados = []

        def _fake(p, write_status=None):
            intentados.append(p)
            return {"rows_updated": 9 if p in periodos_con_cubo else 0}

        monkeypatch.setattr(ops, "SessionLocal", lambda: db)
        monkeypatch.setattr("modules.banking_score.sib_sync.recompute_carteras_metrics", _fake)
        return intentados

    def test_un_corte_sin_cubo_NO_bloquea_al_de_atras(self, db, monkeypatch):
        """LA REGRESIÓN. Con la cabeza sin cubo, el viejo tiene que llegar a intentarse."""
        intentados = self._con_cubo_solo_en(monkeypatch, db, {"2025-03"})
        r = ops._run_sectorial_al_dia({}, None, lambda *_: None)
        assert intentados == ["2025-09", "2025-03"], intentados
        assert r["cargados"] == 1
        assert r["sin_cubo"] == ["2025-09"]

    def test_el_presupuesto_cuenta_CARGADOS_y_no_intentos(self, db, monkeypatch):
        """Con `cortes=1` y la cabeza sin cubo, igual se carga UN corte: el costo está en la
        escritura, no en preguntarle a la fuente."""
        self._con_cubo_solo_en(monkeypatch, db, {"2025-03"})
        r = ops._run_sectorial_al_dia({"cortes": 1}, None, lambda *_: None)
        assert r["cargados"] == 1 and len(r["procesados"]) == 2

    def test_para_de_cargar_al_llegar_al_presupuesto(self, db, monkeypatch):
        """No se convierte en el backfill de 2h30 que el diseño evita: con los dos cortes
        cargables y `cortes=1`, se carga UNO y el otro queda para la próxima."""
        intentados = self._con_cubo_solo_en(monkeypatch, db, {"2025-09", "2025-03"})
        r = ops._run_sectorial_al_dia({"cortes": 1}, None, lambda *_: None)
        assert intentados == ["2025-09"]
        assert r["cargados"] == 1 and r["quedan"] == 1

    def test_una_fuente_caida_no_dispara_un_barrido(self, db_con_muchos_huecos, monkeypatch):
        """Si NINGÚN corte tiene cubo, los intentos se acotan: una operación corta no puede
        volverse un recorrido de los 23 trimestres porque la fuente esté caída.

        La base de este test tiene MÁS huecos que el tope a propósito. Con la fixture chica
        —dos cortes contra un tope de cinco— quitar el tope no cambiaba nada y el test pasaba
        en verde contra el código sin acotar: comprobaba el fixture, no la regla.
        """
        intentados = self._con_cubo_solo_en(monkeypatch, db_con_muchos_huecos, set())
        r = ops._run_sectorial_al_dia({}, None, lambda *_: None)
        assert r["faltaban"] > 1 + ops.INTENTOS_EXTRA, "la fixture no ejercita el tope"
        assert len(intentados) == 1 + ops.INTENTOS_EXTRA, intentados
        assert r["cargados"] == 0 and r["quedan"] == r["faltaban"]

    def test_quedan_cuenta_los_que_siguen_SIN_desglose(self, db, monkeypatch):
        """Un corte intentado y sin cubo NO se descuenta: sigue faltando. Descontarlo haría
        que el contador dijera «cero pendientes» sobre una brecha abierta."""
        self._con_cubo_solo_en(monkeypatch, db, {"2025-03"})
        r = ops._run_sectorial_al_dia({}, None, lambda *_: None)
        assert r["faltaban"] == 2 and r["quedan"] == 1


@pytest.fixture()
def db_incompleto():
    """Un corte CON cubo al que le falta una entidad que presta, y una cambiaria que no.

    Reproduce el punto ciego real: 21 cortes «hechos» a los que les faltaban las mismas dos
    entidades porque el emparejador no reconocía los nombres que el cubo emitía.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    presta = Bank(name="Banco Que Presta", bank_type=BankType.banca_multiple)
    falta = Bank(name="Banco Sin Cubo", bank_type=BankType.banca_multiple)
    cambia = Bank(name="Agente de Cambio", bank_type=BankType.cambiaria)
    s.add_all([presta, falta, cambia])
    s.flush()
    pe = date(2025, 6, 30)
    for b in (presta, falta, cambia):
        s.add(BankingData(bank_id=b.id, period_end=pe))
    # El cubo trae solo a UNO de los dos que prestan. La cambiaria nunca está, y está bien.
    s.add(CarteraSectorial(bank_id=presta.id, period_end=pe,
                           sector="F - CONSTRUCCIÓN", provincia="SANTIAGO", deuda=100))
    s.commit()
    return s


class TestUnCorteINCOMPLETOSeVe:
    """El punto ciego que dejó 21 cortes «hechos» durante cinco años.

    La brecha se computaba comparando conjuntos de CORTES: un trimestre con al menos una
    celda contaba como hecho, y a la operación le era indistinguible de uno completo. Lo
    destapó el rename de FONDESA y el Caribe, que nunca habían entrado al cubo ni una vez
    desde 2021-03-31.
    """

    def test_un_corte_con_cubo_pero_sin_una_entidad_se_marca(self, db_incompleto):
        incompletos = ops.cortes_incompletos(db_incompleto)
        assert list(incompletos) == [date(2025, 6, 30)]
        assert incompletos[date(2025, 6, 30)] == ["Banco Sin Cubo"]

    def test_la_cambiaria_NO_cuenta_como_hueco(self, db_incompleto):
        """Los agentes de cambio y las fiduciarias no otorgan crédito: exigirles cartera
        sectorial marcaría TODOS los cortes como incompletos para siempre. Son 46 de las 89
        entidades del universo supervisado — la regla se volvería inútil."""
        assert "Agente de Cambio" not in ops.cortes_incompletos(db_incompleto)[date(2025, 6, 30)]

    def test_un_corte_COMPLETO_no_aparece(self, db_incompleto):
        """Sin esto, el test de arriba pasaría con una función que devuelve todo siempre."""
        b = db_incompleto.query(Bank).filter_by(name="Banco Sin Cubo").one()
        db_incompleto.add(CarteraSectorial(bank_id=b.id, period_end=date(2025, 6, 30),
                                           sector="A - AGRO", provincia="AZUA", deuda=50))
        db_incompleto.commit()
        assert ops.cortes_incompletos(db_incompleto) == {}

    def test_el_corte_incompleto_se_REINGIERE(self, db_incompleto, monkeypatch):
        """La reparación. Antes ni siquiera entraba a la lista de trabajo."""
        llamados = []
        monkeypatch.setattr(ops, "SessionLocal", lambda: db_incompleto)
        monkeypatch.setattr("modules.banking_score.sib_sync.recompute_carteras_metrics",
                            lambda p, write_status=None: llamados.append(p) or {"rows_updated": 5})
        r = ops._run_sectorial_al_dia({}, None, lambda *_: None)
        assert llamados == ["2025-06"]
        assert r["incompletos"] == {"2025-06": ["Banco Sin Cubo"]}
        assert r["procesados"][0]["faltaban_entidades"] == ["Banco Sin Cubo"]

    def test_reingerir_NO_es_lo_mismo_que_completar(self, db_incompleto, monkeypatch):
        """Si después de reingerir la entidad SIGUE faltando, el corte no se cuenta como
        resuelto y se dice cuál. La fuente no la trae, y reintentar no la va a traer."""
        monkeypatch.setattr(ops, "SessionLocal", lambda: db_incompleto)
        monkeypatch.setattr("modules.banking_score.sib_sync.recompute_carteras_metrics",
                            lambda p, write_status=None: {"rows_updated": 5})
        r = ops._run_sectorial_al_dia({}, None, lambda *_: None)
        assert r["procesados"][0]["siguen_faltando"] == ["Banco Sin Cubo"]
        assert r["siguen_incompletos"] == ["2025-06"]
        assert r["cargados"] == 0, "un corte que sigue incompleto no es trabajo hecho"

    def test_los_VACIOS_se_atienden_primero(self, db_incompleto, monkeypatch):
        """Un corte sin cubo es un hueco mayor que uno al que le falta gente.

        La base tiene los DOS a la vez a propósito: con una que solo tuviera vacíos, invertir
        la prioridad no cambiaría nada y el test pasaría en verde contra el orden equivocado.
        """
        # Un corte VACÍO, posterior al incompleto: reportó y no tiene ni una celda.
        b = db_incompleto.query(Bank).filter_by(name="Banco Que Presta").one()
        db_incompleto.add(BankingData(bank_id=b.id, period_end=date(2025, 9, 30)))
        db_incompleto.commit()
        assert ops.cortes_sin_desglose_sectorial(db_incompleto) == [date(2025, 9, 30)]
        assert list(ops.cortes_incompletos(db_incompleto)) == [date(2025, 6, 30)]

        llamados = []
        monkeypatch.setattr(ops, "SessionLocal", lambda: db_incompleto)
        monkeypatch.setattr("modules.banking_score.sib_sync.recompute_carteras_metrics",
                            lambda p, write_status=None: llamados.append(p) or {"rows_updated": 3})
        ops._run_sectorial_al_dia({}, None, lambda *_: None)
        assert llamados[0] == "2025-09", llamados


class TestUnaAusenciaSeDECLARA:
    """«Todavía no» y «nunca» no son lo mismo, y hasta hoy se reintentaban igual.

    Tras reingerir los 19 cortes (2026-09-02) quedaron cinco donde la fuente sigue sin traer
    a Qik y uno sin Activo. Reintentarlos cada semana no los va a traer: son ausencias
    reales, y lo que corresponde es declararlas con su evidencia.

    Cómo se distingue una ausencia real de un defecto nuestro: un fallo de emparejamiento
    deja a la entidad fuera de TODOS los cortes —le pasó a FONDESA y al Caribe, ausentes en
    los 21— mientras que una ausencia legítima está ACOTADA y es consecutiva.
    """

    def test_una_ausencia_declarada_deja_de_marcarse(self, db_incompleto):
        """Lo declarado no ensucia la lista de trabajo."""
        ops.AUSENCIAS_DECLARADAS["Banco Sin Cubo"] = {
            "cortes": frozenset({date(2025, 6, 30)}),
            "motivo": "prueba", "evidencia": "prueba"}
        try:
            assert ops.cortes_incompletos(db_incompleto) == {}
        finally:
            del ops.AUSENCIAS_DECLARADAS["Banco Sin Cubo"]

    def test_solo_en_LOS_CORTES_declarados(self, db_incompleto):
        """Los cortes van enumerados, no por rango: un corte nuevo NO queda tapado.

        Un rango abierto («desde tal fecha») escondería justo la regresión que esto no debe
        esconder — que la entidad vuelva a faltar donde antes estaba.
        """
        ops.AUSENCIAS_DECLARADAS["Banco Sin Cubo"] = {
            "cortes": frozenset({date(2024, 3, 31)}),      # OTRO corte
            "motivo": "prueba", "evidencia": "prueba"}
        try:
            assert ops.cortes_incompletos(db_incompleto) == {
                date(2025, 6, 30): ["Banco Sin Cubo"]}
        finally:
            del ops.AUSENCIAS_DECLARADAS["Banco Sin Cubo"]

    def test_toda_ausencia_declarada_trae_MOTIVO_y_EVIDENCIA(self):
        """Declarar sin evidencia es encogerse de hombros con más pasos. Misma forma que
        `no_medido` en el control por tamaño y que `dato_pendiente` en los obstáculos."""
        assert ops.AUSENCIAS_DECLARADAS, "el barrido no encontró ninguna declaración"
        for nombre, e in ops.AUSENCIAS_DECLARADAS.items():
            assert e.get("cortes"), f"{nombre} no enumera sus cortes"
            assert all(isinstance(c, date) for c in e["cortes"]), nombre
            assert len(e.get("motivo", "")) > 20, f"{nombre} no explica POR QUÉ falta"
            assert len(e.get("evidencia", "")) > 40, (
                f"{nombre} no dice CÓMO se comprobó. Una ausencia declarada sin evidencia "
                "es indistinguible de un defecto nuestro tapado.")

    def test_las_declaradas_SIGUEN_listadas_en_el_resultado(self, db, monkeypatch):
        """Una ausencia que desaparece del reporte se lee como que el dato está."""
        monkeypatch.setattr(ops, "SessionLocal", lambda: db)
        monkeypatch.setattr("modules.banking_score.sib_sync.recompute_carteras_metrics",
                            lambda p, write_status=None: {"rows_updated": 3})
        r = ops._run_sectorial_al_dia({}, None, lambda *_: None)
        assert "Qik Banco Digital Dominicano" in r["ausencias_declaradas"]
        assert r["ausencias_declaradas"]["Banco Múltiple Activo"] == ["2023-09"]
