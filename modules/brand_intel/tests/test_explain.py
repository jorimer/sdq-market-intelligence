"""El motor explicativo: el porqué económico de lo que el proveedor concluye.

Lo que se protege aquí es la honestidad del reparto. Una conclusión de consumo se explica
con los factores del contrato macro CON SUS VALORES; una de percepción NO se explica con
macro — decir «tu caída de imagen es la inflación» sería inventar, y la negativa es en sí
la lectura. Y la garantía del canal: una conclusión bloqueada por discrepancia jamás
llega al informe.
"""
from types import SimpleNamespace

from modules.brand_intel import service as svc
from modules.brand_intel.engines import explain as xp
from modules.brand_intel.ingest import conclusions as conc


def _c(metric, direction="baja", claim="El consumo se espacia frente a olas previas.",
       kind="hallazgo"):
    return SimpleNamespace(claim=claim, kind=kind, subjects=("Focal",),
                           metric_code=metric, direction=direction, wave_label="")


FACTORS = [
    {"key": "inflacion", "label": "Inflación interanual", "value": 5.35, "unit": "%",
     "direction": "adverso", "magnitude": "bajo", "reading": "5.35%, sobre meta"},
    {"key": "imae", "label": "Actividad económica (IMAE)", "value": 4.69, "unit": "%",
     "direction": "favorable", "magnitude": "moderado", "reading": "4.69%"},
    {"key": "tpm", "label": "Tasa de Política Monetaria", "value": 5.25, "unit": "%",
     "direction": "neutral", "magnitude": "bajo", "reading": "5.25%"},
    {"key": "fx", "label": "Depreciación cambiaria (interanual)", "value": -3.03,
     "unit": "%", "direction": "favorable", "magnitude": "alto", "reading": "-3.03%"},
    {"key": "remesas", "label": "Remesas familiares (interanual)", "value": None,
     "unit": "%", "direction": "n/d", "magnitude": "n/d", "reading": "n/d"},
]


def test_una_conclusion_de_consumo_recibe_su_lectura_con_valores():
    out = xp.explain_conclusions([_c("reach_7d")], FACTORS)
    assert len(out["explicadas"]) == 1
    lectura = out["explicadas"][0]["reading"]
    # La caída con inflación adversa es "consistente con el bolsillo", con el valor
    # del período incrustado — no una lista genérica de factores.
    assert "5.35%" in lectura and "bolsillo" in lectura
    # Y el entorno queda declarado UNA vez, aparte, con sus valores.
    assert out["entorno"]["inflacion"]["value"] == 5.35


def test_el_ticket_se_lee_por_inflacion_y_tipo_de_cambio():
    out = xp.explain_conclusions([_c("ticket_avg", "sube")], FACTORS)
    lectura = out["explicadas"][0]["reading"]
    assert "traslado de precios" in lectura
    assert "insumos importados" in lectura
    assert "IMAE" not in lectura                          # no es su canal


def test_percepcion_no_se_explica_con_macro():
    """La negativa es la honestidad del motor: imagen no es inflación."""
    out = xp.explain_conclusions(
        [_c("favourite_place", "baja", "Focal pierde preferencia declarada.")], FACTORS)
    assert out["explicadas"] == []
    assert len(out["competitivas"]) == 1


def test_caida_de_percepcion_en_entorno_favorable_es_el_insight():
    out = xp.explain_conclusions(
        [_c("favourite_place", "baja", "Focal pierde preferencia declarada.")],
        FACTORS, environment_stance="favorable")
    lectura = out["competitivas"][0]["reading"]
    assert "favorable" in lectura and "competitiva" in lectura


def test_un_factor_sin_valor_no_entra_al_entorno():
    """Remesas viene n/d en el contrato: no puede aparecer como explicación."""
    out = xp.explain_conclusions([_c("reach_7d")], FACTORS)
    assert "remesas" not in out["entorno"]


def test_direccion_contraria_produce_lectura_distinta():
    """La misma inflación acompaña una caída y agrava el mérito de un avance: si las
    dos direcciones produjeran la misma frase, la capa sería relleno."""
    baja = xp.explain_conclusions([_c("reach_7d", "baja")], FACTORS)
    sube = xp.explain_conclusions([_c("reach_7d", "sube")], FACTORS)
    assert baja["explicadas"][0]["reading"] != sube["explicadas"][0]["reading"]
    assert "meritorio" in sube["explicadas"][0]["reading"]


def test_un_perfil_sin_direccion_no_recibe_capa():
    """«Mayor incidencia en NSE alto» no afirma movimiento: pegarle la inflación sería
    relleno — el defecto exacto de la primera versión de este motor."""
    out = xp.explain_conclusions(
        [_c("reach_7d", "", "Mayor incidencia de consumo en NSE alto.")], FACTORS)
    assert out["explicadas"] == []
    assert len(out["sin_capa"]) == 1


def test_sin_contrato_macro_se_degrada_declarado():
    out = xp.explain_conclusions([_c("reach_7d")], [])
    assert out["explicadas"] == []
    assert out["sin_capa"] and "contrato macro" in out["sin_capa"][0]["reason"]


def test_recomendaciones_y_contexto_no_se_explican():
    out = xp.explain_conclusions(
        [_c("reach_7d", kind="recomendacion"), _c("reach_7d", kind="contexto")], FACTORS)
    assert not out["available"]


def test_conclusion_sin_metrica_queda_citable_pero_sin_capa():
    out = xp.explain_conclusions([_c(None, "", "La categoría se mantiene plana.")],
                                 FACTORS)
    assert out["sin_capa"][0]["claim"] == "La categoría se mantiene plana."


# ── la garantía del canal, de punta a punta ──────────────────────────

def test_una_conclusion_bloqueada_no_llega_a_la_capa_explicativa(db, engagement):
    """El informe llama a `usable_conclusions`, no a la tabla: si la discrepancia está
    abierta, la conclusión simplemente no existe para el redactor."""
    from modules.brand_intel.models.models import BrandObservation, BrandWave

    w2 = (db.query(BrandWave).filter(BrandWave.engagement_id == engagement.id,
                                     BrandWave.code == "w2").one())
    obs = (db.query(BrandObservation)
           .filter(BrandObservation.engagement_id == engagement.id,
                   BrandObservation.wave_id == w2.id,
                   BrandObservation.brand_slug == "focal",
                   BrandObservation.metric_code == "reach_7d").one())
    obs.value = 90.0                       # movimiento significativo: 40 → 90
    db.flush()
    conc.store_conclusions(db, str(engagement.id), [conc.Conclusion(
        claim="Focal reduce su incidencia de consumo.", page_number=14,
        kind="hallazgo", subjects=("Focal",), topic="", metric_code="reach_7d",
        direction="baja", wave_label="Ola 2", confident=True,
    )])
    db.flush()
    svc.contrast_conclusions(db, str(engagement.id))   # abre la discrepancia
    db.flush()

    out = svc.explanations_analysis(db, str(engagement.id))
    assert out["conclusions_blocked"] == 1
    assert all("incidencia" not in e["claim"]
               for e in out["explicadas"] + out["competitivas"] + out["sin_capa"])


def test_el_informe_lleva_la_capa_explicativa(db, engagement):
    from modules.brand_intel import report as rpt

    conc.store_conclusions(db, str(engagement.id), [conc.Conclusion(
        claim="Focal pierde preferencia declarada frente a la ola previa.",
        page_number=19, kind="hallazgo", subjects=("Focal",), topic="",
        metric_code="favourite_place", direction="baja", wave_label="Ola 2",
        confident=True,
    )])
    db.flush()
    p = rpt.build_report(db, engagement)
    x = p["sections"]["explanations"]
    assert x["available"] is True
    assert len(x["competitivas"]) == 1

    html = rpt.render_html(p)
    assert "pierde preferencia declarada" in html
    # La lámina NO viaja en la prosa del cliente: el recibo vive en el registro.
    assert "Lámina 19" not in html and "lámina 19" not in html
    # Y las secciones que competían con el proveedor ya no están.
    assert "Tamaño de la categoría y share" not in html
    assert "Conversión por escalón" not in html
