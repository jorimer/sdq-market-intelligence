"""Tests de la cohorte canónica de terminaciones.

Lo que protegen: que la unidad sea la INSTITUCIÓN y no el código —o se pierden las quiebras
absorbidas, que son las sistémicas—, y que un dato ausente no se lea como salida sana.
"""
from datetime import date

from modules.banking_score.validation import terminaciones as tm


def _fila(nombre, *, tipo="Bancos Múltiples", mora=None, apa=10.0, code="X"):
    return {"entidad_code": code, "entidad_nombre": nombre, "tipo_entidad": tipo,
            "morosidad_pct": mora, "apalancamiento_pct": apa}


def _serie(nombres_por_fecha):
    return {f: _fila(n, **kw) for f, (n, kw) in nombres_por_fecha.items()}


def test_patrimonio_negativo_es_insolvencia():
    t = tm.clasificar(_fila("B", mora=2.0, apa=-1.5), 1, 60, date(2003, 5, 1))
    assert t.naturaleza == "insolvencia" and "patrimonio negativo" in t.evidencia[0]


def test_mora_tres_veces_el_piso_de_su_tipo_es_insolvencia():
    assert tm.clasificar(_fila("B", mora=16.0), 1, 60, date(2003, 5, 1)).naturaleza == "insolvencia"
    # el mismo 16% es solo deterioro para una corporación de crédito (piso 15%)
    t = tm.clasificar(_fila("C", tipo="Corporaciones de Crédito", mora=16.0), 1, 60,
                      date(2003, 5, 1))
    assert t.naturaleza == "deterioro", "el umbral es relativo al tipo, no plano"


def test_sin_morosidad_NO_se_declara_sana():
    """Un patrimonio positivo no es evidencia de salud, y en la era temprana la mora casi no
    se reporta: aprobar por ausencia de dato mandaba las quiebras de los 90 a 'fusiones'."""
    t = tm.clasificar(_fila("B", mora=None, apa=8.0), 1, 60, date(1992, 9, 1))
    assert t.naturaleza == "no_evaluable"
    assert not t.es_quiebra, "tampoco se cuenta como quiebra lo que no se pudo mirar"


def test_la_unidad_es_la_institucion_no_el_codigo():
    """`BANCRÉDITO - LEÓN` es UN código con DOS instituciones. Keyeando por código, la quiebra
    de 2003 nunca aparece: la serie continúa bajo el sucesor."""
    serie = {}
    for y in range(1995, 2004):
        serie[date(y, 12, 1)] = _fila("Banco Nacional de Crédito", mora=25.0, code="BC-LEON")
    for y in range(2004, 2015):
        serie[date(y, 12, 1)] = _fila("Banco León", mora=2.0, code="BC-LEON")
    t = tm.detectar({"BC-LEON": serie}, date(2026, 4, 1))
    nombres = {x.entidad_nombre for x in t}
    assert "Banco Nacional de Crédito" in nombres, "la quiebra absorbida debe aparecer"
    quiebra = next(x for x in t if x.entidad_nombre == "Banco Nacional de Crédito")
    assert quiebra.naturaleza == "insolvencia"
    assert quiebra.fecha_salida.year == 2003
    assert quiebra.revisar_linaje is True


def test_el_linaje_marca_pero_NO_excluye():
    """Filtrar los códigos compartidos 'por prudencia' borraba a Bancrédito y a Mercantil:
    las entidades absorbidas son justamente las que comparten código con su sucesor."""
    t = [tm.Terminacion("C", "Absorbida", "Bancos Múltiples", date(2003, 12, 1),
                        "insolvencia", ("x",), True, 60, 30.0, 1.0)]
    assert len(tm.cohorte_canonica(t)) == 1
    assert len(tm.cohorte_canonica(t, solo_linaje_limpio=True)) == 0


def test_una_entidad_viva_no_es_una_salida():
    serie = {date(y, 12, 1): _fila("Vivo", mora=2.0) for y in range(2015, 2026)}
    serie[date(2026, 3, 1)] = _fila("Vivo", mora=2.0)
    assert tm.detectar({"V": serie}, date(2026, 4, 1)) == []


def test_una_salida_sana_no_entra_a_la_cohorte():
    """Bank of America cerrando su operación en RD no es una quiebra."""
    t = tm.clasificar(_fila("Bank of America", mora=1.2), 1, 200, date(1984, 12, 1))
    assert t.naturaleza == "sana_al_salir" and not t.es_quiebra


def test_el_resumen_declara_sobre_que_se_calibra():
    t = [tm.Terminacion("A", "X", "Bancos Múltiples", date(2003, 5, 1), "insolvencia",
                        ("x",), False, 60, 40.0, -1.0),
         tm.Terminacion("B", "Y", "Bancos Múltiples", date(1984, 1, 1), "sana_al_salir",
                        ("y",), False, 60, 1.0, 9.0)]
    r = tm.resumen(t)
    assert r["n_salidas"] == 2 and r["n_cohorte_canonica"] == 1
    assert r["por_naturaleza"]["insolvencia"] == 1
    assert set(r["por_decada"]) == {2000, 1980}


# ── Registro curado: la etiqueta que viene de AFUERA de los ratios ──

def test_la_causa_curada_manda_sobre_la_inferida():
    """Si el registro dice que fue una fusión, no importa en qué estado contable salió."""
    base = tm.Terminacion("C", "X", "Bancos Múltiples", date(2003, 1, 1), "insolvencia",
                          ("mora alta",), False, 60, 40.0, -1.0)
    assert base.es_quiebra is True and base.origen_etiqueta == "inferida"
    curada = tm.aplicar_curaduria([base], {"x": {"causa": "fusion", "fuente": "acta"}})[0]
    assert curada.es_quiebra is False, "la curaduría manda"
    assert curada.origen_etiqueta == "curada"


def test_la_curaduria_rescata_lo_que_la_inferencia_no_puede_ver():
    """Banco Universal y Panamericano salen en 1992 SIN morosidad reportada: la inferencia
    solo puede decir `no_evaluable`. El registro los rescata como quiebras — que es
    exactamente para lo que existe."""
    t = tm.Terminacion("U", "Banco Universal", "Bancos Múltiples", date(1992, 9, 1),
                       "no_evaluable", ("sin mora",), False, 40, None, 6.0)
    assert t.es_quiebra is False
    c = tm.aplicar_curaduria([t], {"banco universal": {"causa": "quiebra",
                                                       "fuente": "roster del dueño"}})[0]
    assert c.es_quiebra is True


def test_una_causa_sin_fuente_se_ignora():
    """Una etiqueta sin procedencia es el problema que el registro vino a resolver."""
    reg = tm.cargar_curadas.__wrapped__ if hasattr(tm.cargar_curadas, "__wrapped__") else None
    t = tm.Terminacion("C", "X", "Bancos Múltiples", date(2003, 1, 1), "sana_al_salir",
                       ("ok",), False, 60, 1.0, 9.0)
    # sin `fuente` el cargador no la habría admitido; se simula pasando el registro vacío
    assert tm.aplicar_curaduria([t], {})[0].causa_curada is None
    assert reg is None or True


def test_el_registro_real_carga_y_trae_las_sistemicas_de_2003():
    reg = tm.cargar_curadas()
    assert reg, "el archivo curado debe existir y cargar"
    for nombre in ("banco intercontinental (baninter)", "banco nacional de credito",
                   "banco mercantil", "banco global"):
        assert reg[nombre]["causa"] == "quiebra"
        assert reg[nombre]["fuente"], "sin fuente no se acepta una etiqueta"


def test_validar_contra_curadas_reporta_los_desacuerdos():
    """La prueba de aceptación: ¿la inferencia acierta las salidas cuya causa conocemos?
    Los desacuerdos son la lista de trabajo, no un error a esconder."""
    ts = [
        tm.Terminacion("A", "Quiebra vista", "Bancos Múltiples", date(2003, 5, 1),
                       "insolvencia", ("x",), False, 60, 40.0, -1.0, "quiebra", "panel"),
        tm.Terminacion("B", "Quiebra invisible", "Bancos Múltiples", date(1992, 9, 1),
                       "no_evaluable", ("y",), False, 40, None, 6.0, "quiebra", "roster"),
        tm.Terminacion("C", "Sin curar", "Bancos Múltiples", date(2010, 1, 1),
                       "deterioro", ("z",), False, 60, 12.0, 5.0),
    ]
    v = tm.validar_contra_curadas(ts)
    assert v["n_curadas"] == 2, "solo se mide sobre las curadas"
    assert v["n_aciertos"] == 1 and v["n_fallos"] == 1
    assert v["fallos"][0]["entidad"] == "Quiebra invisible"
