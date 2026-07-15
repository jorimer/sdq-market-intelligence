"""Regresión del Hallazgo 2 del piloto P4-P6: la MISMA variable (TPM) la citan dos motores
(monetary_policy y macro/IRMP) con vintage y etiqueta cualitativa distintos. Se reconcilia en la
síntesis a UNA sola línea (cifra autoritativa del BCRD + lectura del IRMP), sin duplicar el número
en el mismo informe. Estructural: empareja por Evidence.variable, no por texto."""
from shared.registry.signals import REAL
from shared.research.data_pull import TPM_VARIABLE
from shared.research.deep_report import _reconcile_shared_variables
from shared.research.models import Evidence


def _monetary_pull():
    from shared.research.data_pull import EnginePull
    return EnginePull(
        sector_key="monetary_policy", entity_label="Política monetaria", period="2026-06-30",
        source="BCRD", ok=True,
        payload={"latest": {"tpm": 5.2, "sentido": "hold", "fecha": "2026-06-30"}},
        evidence=[Evidence(text="Política monetaria (BCRD): TPM en 5.2% (hold) al 2026-06-30.",
                           source="BCRD", kind="engine", state=REAL, score=95.0,
                           variable=TPM_VARIABLE)])


def _macro_pull(mac_tpm_value=5.2):
    from shared.research.data_pull import EnginePull
    return EnginePull(
        sector_key="macro", entity_label="Macro & riesgo-país", period="2026-03-31",
        source="BCRD/IRMP", ok=True,
        payload={"irmp_band": "Moderado", "irmp_score": 55.0,
                 "factors": [{"key": "inflation", "label": "Inflación", "value": 3.9,
                              "direction": "neutral"},
                             {"key": "policy_rate", "label": "Tasa de Política Monetaria",
                              "value": mac_tpm_value, "direction": "neutral"}]},
        evidence=[Evidence(text="Riesgo-país / macro: banda Moderado (IRMP 55.0) al 2026-03-31.",
                           source="BCRD/IRMP", kind="engine", state=REAL, score=94.0),
                  Evidence(text="Tasa de Política Monetaria: 5.2 · neutral.",
                           source="BCRD/IRMP", kind="engine", state=REAL, score=88.0,
                           variable="policy_rate")])


def _tpm_lines(pull):
    return [e for e in pull.evidence if e.variable == TPM_VARIABLE]


# ─── la TPM aparece UNA sola vez tras reconciliar ──────────────────────
def test_tpm_cited_once_after_reconcile():
    mon, mac = _monetary_pull(), _macro_pull()
    live = [mac, mon]   # orden arbitrario (macro primero, como en un pull de contexto)
    _reconcile_shared_variables(live)
    # el macro ya NO emite su línea de TPM (se reconcilió a la del motor monetario).
    assert _tpm_lines(mac) == []
    # el motor monetario emite UNA línea consolidada.
    assert len(_tpm_lines(mon)) == 1
    # el factor no-TPM del macro (inflación) se conserva intacto.
    assert any("banda Moderado" in e.text for e in mac.evidence)


def test_consolidated_line_has_both_readings_and_authoritative_vintage():
    mon, mac = _monetary_pull(), _macro_pull()
    _reconcile_shared_variables([mon, mac])
    line = _tpm_lines(mon)[0].text
    assert "5.2%" in line
    assert "hold" in line                # lectura de la DECISIÓN del BCRD (autoritativa)
    assert "2026-06-30" in line          # vintage de la decisión (fechado por reunión)
    assert "IRMP" in line and "neutral" in line   # lectura cualitativa del IRMP


def test_discrepant_macro_value_is_surfaced_not_hidden():
    # si la serie del IRMP registra un nivel distinto (vintage/escala), se MUESTRA, no se oculta.
    mon, mac = _monetary_pull(), _macro_pull(mac_tpm_value=5.5)
    _reconcile_shared_variables([mon, mac])
    line = _tpm_lines(mon)[0].text
    assert "5.2%" in line                # la autoritativa
    assert "5.5%" in line                # y la discrepante del IRMP, visible


# ─── no-op cuando falta un motor o la etiqueta ─────────────────────────
def test_noop_without_macro():
    mon = _monetary_pull()
    _reconcile_shared_variables([mon])
    assert _tpm_lines(mon)[0].text.startswith("Política monetaria")   # intacta


def test_noop_without_tagged_evidence():
    from shared.research.data_pull import EnginePull
    mon = _monetary_pull()
    # macro sin factor policy_rate (no hay variable compartida) → nada que reconciliar.
    mac = EnginePull(sector_key="macro", entity_label="Macro", period="2026-03-31",
                     source="BCRD/IRMP", ok=True,
                     payload={"factors": [{"key": "inflation", "label": "Inflación",
                                           "value": 3.9, "direction": "neutral"}]},
                     evidence=[Evidence(text="Riesgo-país: banda Moderado.", source="BCRD/IRMP",
                                        kind="engine", state=REAL, score=94.0)])
    _reconcile_shared_variables([mon, mac])
    assert len(_tpm_lines(mon)) == 1     # la línea monetaria queda tal cual (no consolidada)
    assert "postura en el IRMP" not in _tpm_lines(mon)[0].text
