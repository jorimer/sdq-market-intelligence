"""Tests de la calibración de la concentración contra deterioro de cartera.

Lo que protegen no es la aritmética: es que el módulo se NIEGUE a publicar un peso cuando el
dato no lo sostiene. Un coeficiente ajustado sobre cinco eventos no es un peso, es ruido con
decimales — y esa es exactamente la clase de cifra que este trabajo vino a dejar de producir.
"""
from datetime import date

from modules.banking_score.validation import concentracion_calibration as cc


def _q(n, y0=2021):
    """n trimestres consecutivos desde marzo de *y0*."""
    out, y, m = [], y0, 3
    for _ in range(n):
        out.append(date(y, m, 30 if m in (6, 9) else 31))
        m += 3
        if m > 12:
            m, y = 3, y + 1
    return out


def _ent(qs, *, conc, mora, castigos=None, solv=None, roa=None):
    def _s(vals):
        return {q.isoformat(): v for q, v in zip(qs, vals)} if vals else {}
    return {"tipo": "banca_multiple", "concentracion_top10": _s(conc),
            "morosidad": _s(mora), "castigos_pct": _s(castigos),
            "solvencia": _s(solv), "roa": _s(roa)}


def test_deterioro_crediticio_por_salto_de_mora():
    qs = _q(6)
    mora = {q: v for q, v in zip(qs, [2.0, 2.0, 2.0, 2.0, 3.5, 3.5])}
    assert cc.deterioro_crediticio(mora, {}, qs[0], qs[1:5]) is True


def test_deterioro_crediticio_no_dispara_por_variacion_menor():
    qs = _q(6)
    mora = {q: v for q, v in zip(qs, [2.0, 2.1, 2.2, 2.3, 2.4, 2.5])}
    assert cc.deterioro_crediticio(mora, {}, qs[0], qs[1:5]) is False


def test_deterioro_crediticio_tambien_por_castigos():
    qs = _q(6)
    mora = {q: 2.0 for q in qs}
    cast = {q: v for q, v in zip(qs, [0.2, 0.3, 0.4, 0.9, 0.9, 0.9])}
    assert cc.deterioro_crediticio(mora, cast, qs[0], qs[1:5]) is True


def test_el_deterioro_amplio_reusa_las_reglas_ya_validadas():
    """Mora ×2, solvencia bajo el piso, ROA<0 en dos trimestres — las tres de
    `outcomes_derivation`, no una definición nueva."""
    qs = _q(6)
    plano = {q: 2.0 for q in qs}
    assert cc.deterioro_amplio({q: v for q, v in zip(qs, [2.0, 2, 2, 2, 4.1, 4.1])},
                               {}, {}, qs[0], qs[1:5]) is True
    assert cc.deterioro_amplio(plano, {q: 9.0 for q in qs}, {}, qs[0], qs[1:5]) is True
    assert cc.deterioro_amplio(plano, {}, {q: -0.1 for q in qs}, qs[0], qs[1:5]) is True
    assert cc.deterioro_amplio(plano, {q: 15.0 for q in qs}, {q: 0.02 for q in qs},
                               qs[0], qs[1:5]) is False


def test_una_base_sin_horizonte_completo_no_entra():
    """Sin el horizonte entero no se sabe si el desenlace no ocurrió o no se pudo observar.
    Contarlo como 'no ocurrió' sesga la tasa de eventos a la baja."""
    qs = _q(6)
    panel = {"A": _ent(qs, conc=[40] * 6, mora=[2.0] * 6)}
    X, y, g = cc.construir_matriz(panel)
    # 6 períodos, horizonte de 4 ⇒ solo las bases con 4 trimestres por delante
    assert len(y) == 2


def test_pocos_eventos_NO_devuelve_peso():
    """El resultado más probable y el más importante de reportar bien."""
    qs = _q(12)
    panel = {f"E{i}": _ent(qs, conc=[30 + i] * 12, mora=[2.0] * 12) for i in range(8)}
    ev = cc.calibrar(panel)
    assert ev.identificable is False
    assert ev.coef_estandarizado is None
    assert "insuficientes" in (ev.motivo or "")


def test_eventos_en_pocas_entidades_NO_devuelve_peso():
    """Veinte eventos de tres bancos no son veinte observaciones: la unidad es la entidad."""
    qs = _q(16)
    panel = {}
    for i in range(10):
        malo = i < 3
        mora = [2.0] * 4 + ([6.0] * 12 if malo else [2.0] * 12)
        panel[f"E{i}"] = _ent(qs, conc=[60 if malo else 20] * 16, mora=mora)
    ev = cc.calibrar(panel)
    assert ev.identificable is False


def test_el_intervalo_se_bootstrapea_por_entidad_no_por_observacion():
    """Remuestrear observaciones trataría 20 trimestres del mismo banco como 20 datos
    independientes y estrecharía el intervalo de forma falsa."""
    import inspect
    src = inspect.getsource(cc.calibrar)
    assert "rng.choice(entidades" in src, "el bootstrap remuestrea ENTIDADES"


def test_la_evidencia_nunca_es_un_numero_suelto():
    """Un peso sin su n, su AUC y su intervalo es la clase de cifra que este trabajo vino a
    dejar de producir — la misma que `ALERT_WEIGHTS` tenía sin artefacto."""
    campos = set(cc.Evidencia.__dataclass_fields__)
    assert {"n_obs", "n_eventos", "n_entidades", "auc_loeo", "ic95", "identificable"} <= campos


def test_el_modulo_no_exporta_un_peso_para_pegar_en_alert_weights():
    """Un peso medido contra OTRO desenlace y sobre OTRA ventana no es intercambiable con los
    siete. Mezclarlos sin declararlo sería fabricar coherencia."""
    prohibidos = [n for n in dir(cc)
                  if n.isupper() and "WEIGHT" in n or n.lower() in ("peso", "peso_concentracion")]
    assert not prohibidos


def test_la_etiqueta_viaja_con_el_resultado():
    """Cuál desenlace se midió es parte del resultado: la misma cifra significa cosas
    distintas contra deterioro crediticio que contra distress amplio."""
    qs = _q(12)
    panel = {f"E{i}": _ent(qs, conc=[30] * 12, mora=[2.0] * 12) for i in range(6)}
    assert cc.calibrar(panel, "credito").etiqueta == "credito"
    assert cc.calibrar(panel, "amplio").etiqueta == "amplio"
