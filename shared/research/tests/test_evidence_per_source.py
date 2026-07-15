"""Regresión del Hallazgo 5 (piloto P7-P11): `_evidence_lines` descartaba evidencia de ejes
legítimamente matcheados cuando una pregunta agrupa 2+ sectores en una sola sub-pregunta.

Mecanismo: `_merge_engine_evidence` antepone la evidencia de cada motor, así el motor procesado
al final queda al frente; la truncación plana `sq.evidence[:3]` copaba los 3 cupos con ese motor
y los demás (aunque anclaran el estado REAL) no aportaban ninguna línea visible. El fix garantiza
≥1 línea por FUENTE distinta (round-robin). Se usa el TEXTO LITERAL de las 2 preguntas que lo
reprodujeron 2/2 en vivo."""
from shared.registry.signals import REAL
from shared.research.assemble import _evidence_lines
from shared.research.data_pull import EnginePull
from shared.research.models import Evidence, SubQuestion
from shared.research.orchestrator import _merge_engine_evidence

# Texto literal de las 2 preguntas que reprodujeron el bug en vivo.
Q_TURISMO_MINERIA_CONSTRUCCION = (
    "¿Qué papel juegan el turismo, la minería y la construcción en el crecimiento dominicano, "
    "y cómo se compara ese desempeño con el promedio de Centroamérica y el Caribe?")
Q_ZONAS_FRANCAS_COMERCIO = (
    "¿Cuál es el desempeño reciente de las zonas francas y el comercio exterior dominicano, "
    "y qué papel juegan frente al resto de la economía?")


def _ev(source, text, n):
    """n evidencias REAL de una misma fuente (un motor emite todas con su fuente autoritativa)."""
    return [Evidence(text=f"{text} #{i}", source=source, kind="engine", state=REAL, score=90.0)
            for i in range(n)]


def _pull(sk, label, source, n):
    return EnginePull(sector_key=sk, entity_label=label, period="2026-03", source=source,
                      payload={"x": 1}, evidence=_ev(source, f"{label} dato", n), ok=True)


def _sources_in(rendered: str, sources) -> None:
    for s in sources:
        assert s in rendered, f"falta la fuente {s!r} en la evidencia renderizada:\n{rendered}"


# ─── el fix directo sobre _evidence_lines ──────────────────────────────
def test_evidence_lines_guarantees_one_per_source():
    # construcción trae 3 (copaba los 3 cupos con el bug), turismo trae 2, macro 1.
    sq = SubQuestion(text=Q_TURISMO_MINERIA_CONSTRUCCION, state=REAL)
    sq.evidence = (_ev("MIVHED·BCRD", "construcción m2 licenciados", 3)
                   + _ev("MITUR·BCRD", "turismo llegadas", 2)
                   + _ev("BCRD/IRMP", "macro banda", 1))
    rendered = _evidence_lines(sq)
    _sources_in(rendered, ["MIVHED·BCRD", "MITUR·BCRD", "BCRD/IRMP"])


def test_single_source_behavior_unchanged():
    # una sola fuente con 5 evidencias sigue mostrando 3 líneas (no se infla el informe).
    sq = SubQuestion(text="pregunta de un solo eje", state=REAL)
    sq.evidence = _ev("MIVHED·BCRD", "construcción", 5)
    rendered = _evidence_lines(sq)
    assert len(rendered.strip().splitlines()) == 3


def test_budget_expands_to_number_of_sources():
    # 4 fuentes, cada una 1 evidencia → 4 líneas (el presupuesto se expande, no cae ninguna).
    sq = SubQuestion(text="cuatro ejes", state=REAL)
    sq.evidence = (_ev("A", "a", 1) + _ev("B", "b", 1) + _ev("C", "c", 1) + _ev("D", "d", 1))
    rendered = _evidence_lines(sq)
    _sources_in(rendered, ["A", "B", "C", "D"])
    assert len(rendered.strip().splitlines()) == 4


# ─── end-to-end: merge (que antepone) + render, con las preguntas reales ─
def test_repro1_turismo_construccion_both_visible_after_merge():
    # el orden de merge sigue live/PRODUCT_CATALOG; construcción (3 ev) queda al frente y antes
    # tapaba a turismo. Ahora ambos deben aparecer.
    pulls = [
        _pull("tourism", "Turismo", "MITUR·BCRD", 2),
        _pull("construction", "Construcción", "MIVHED·BCRD", 3),
        _pull("macro", "Macro & riesgo-país", "BCRD/IRMP", 1),
    ]
    sq = SubQuestion(text=Q_TURISMO_MINERIA_CONSTRUCCION, state="gap")
    _merge_engine_evidence([sq], pulls)
    assert sq.state == REAL
    rendered = _evidence_lines(sq)
    _sources_in(rendered, ["MITUR·BCRD", "MIVHED·BCRD"])   # turismo Y construcción visibles


def test_repro2_zonas_francas_comercio_both_visible_after_merge():
    pulls = [
        _pull("trade", "Comercio exterior", "DGA·ONE", 2),
        _pull("free_zones", "Zonas francas", "CNZFE·ONE", 3),
        _pull("macro", "Macro & riesgo-país", "BCRD/IRMP", 1),
    ]
    sq = SubQuestion(text=Q_ZONAS_FRANCAS_COMERCIO, state="gap")
    _merge_engine_evidence([sq], pulls)
    assert sq.state == REAL
    rendered = _evidence_lines(sq)
    _sources_in(rendered, ["CNZFE·ONE", "DGA·ONE"])        # free_zones Y trade visibles
