"""La lectura y el guardado de las conclusiones del proveedor.

Lo que estos tests protegen no es el formato: es el **recibo**. El informe va a decir «el
proveedor concluye X» en un documento que llega a su cliente, así que una conclusión sin
texto literal o con la lámina equivocada no puede llegar a guardarse. Casi todo lo de aquí
comprueba que lo dudoso se descarta en vez de guardarse a medias.
"""
import json
from typing import Any, Dict, List

import pytest

from modules.brand_intel.ingest import conclusions as conc
from modules.brand_intel.models.models import BrandConclusion


class _Block:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, payload: Any, stop_reason: str = "end_turn"):
        self.stop_reason = stop_reason
        body = payload if isinstance(payload, str) else json.dumps(payload)
        self.content = [_Block(body)]


class _FakeClient:
    """Un doble que devuelve respuestas preparadas y anota lo que se le pidió."""

    def __init__(self, *responses: _Response):
        self._queued = list(responses)
        self.prompts: List[str] = []
        self.messages = self

    def create(self, **kwargs: Any) -> _Response:
        self.prompts.append(kwargs["messages"][0]["content"][0]["text"])
        return self._queued.pop(0)


def _row(**over: Any) -> Dict[str, Any]:
    base = {
        "claim": "McDonald's mantiene el liderazgo como marca favorita.",
        "page_number": 19, "kind": "hallazgo", "subjects": ["McDonald's"],
        "topic": "lugar favorito", "metric_code": "", "direction": "estable",
        "wave_label": "Mar '26", "confident": True,
    }
    base.update(over)
    return base


def _texts(n: int = 20) -> List[str]:
    return [f"Lámina {i} con texto suficiente para no estar vacía." for i in range(1, n + 1)]


# ─────────────────────────── lectura ───────────────────────────

def test_lee_las_afirmaciones_con_su_lamina():
    client = _FakeClient(_Response({"conclusions": [_row()]}))
    found = conc.read_conclusions(_texts(), client=client)

    assert len(found) == 1
    assert found[0].page_number == 19
    assert found[0].subjects == ("McDonald's",)
    assert found[0].claim.startswith("McDonald's mantiene")


def test_el_texto_del_mazo_va_rotulado_por_lamina():
    """El modelo debe devolver la lámina, así que tiene que verla numerada."""
    client = _FakeClient(_Response({"conclusions": []}))
    conc.read_conclusions(["primera lámina", "segunda lámina"], client=client)

    prompt = client.prompts[0]
    assert "--- Lámina 1 ---" in prompt
    assert "--- Lámina 2 ---" in prompt


def test_un_mazo_sin_capa_de_texto_no_llama_al_modelo():
    """Un mazo escaneado como imágenes es legítimo: su ingesta de cifras debe seguir."""
    client = _FakeClient()          # sin respuestas: si llamara, reventaría
    assert conc.read_conclusions(["", "   ", ""], client=client) == []
    assert client.prompts == []


def test_descarta_la_conclusion_cuya_lamina_no_existe():
    """Sin lámina buena no hay recibo, y sin recibo no se puede citar al proveedor."""
    client = _FakeClient(_Response({"conclusions": [
        _row(page_number=999), _row(page_number=0), _row(page_number=5),
    ]}))
    found = conc.read_conclusions(_texts(20), client=client)

    assert [c.page_number for c in found] == [5]


def test_descarta_la_afirmacion_sin_texto_citable():
    client = _FakeClient(_Response({"conclusions": [
        _row(claim=""), _row(claim="Sube."), _row(),
    ]}))
    assert len(conc.read_conclusions(_texts(), client=client)) == 1


def test_normaliza_tipo_y_direccion_desconocidos():
    """Un valor fuera del vocabulario no se guarda como está: se cae al caso neutro."""
    client = _FakeClient(_Response({"conclusions": [
        _row(kind="veredicto", direction="lateral"),
    ]}))
    found = conc.read_conclusions(_texts(), client=client)

    assert found[0].kind == "hallazgo"
    assert found[0].direction == ""


def test_una_frase_repetida_en_dos_laminas_se_guarda_dos_veces():
    """Misma frase, láminas distintas: son dos apariciones reales, no un duplicado."""
    client = _FakeClient(_Response({"conclusions": [
        _row(page_number=7), _row(page_number=19),
    ]}))
    assert len(conc.read_conclusions(_texts(), client=client)) == 2


# ─────────────────────── respuesta cortada ───────────────────────

def test_si_la_respuesta_se_corta_parte_el_mazo_y_reintenta():
    """Cuántas conclusiones trae un mazo no se sabe antes de leerlo.

    Confiar en un tope de salida deja el fallo latente: cuando ocurra llega un JSON
    truncado y se pierde la lectura entera. Partir por láminas la recupera, y cada tramo
    conserva la numeración real — la lámina que acompaña a cada frase sigue siendo cierta.
    """
    client = _FakeClient(
        _Response("{ truncado", stop_reason="max_tokens"),
        _Response({"conclusions": [_row(page_number=2)]}),
        _Response({"conclusions": [_row(page_number=8)]}),
    )
    found = conc.read_conclusions(_texts(10), client=client)

    assert [c.page_number for c in found] == [2, 8]
    assert "--- Lámina 6 ---" not in client.prompts[1]     # primera mitad: 1-5
    assert "--- Lámina 6 ---" in client.prompts[2]         # segunda mitad: 6-10


def test_al_partir_no_se_duplica_la_misma_frase_de_la_misma_lamina():
    client = _FakeClient(
        _Response("{ truncado", stop_reason="max_tokens"),
        _Response({"conclusions": [_row(page_number=2)]}),
        _Response({"conclusions": [_row(page_number=2)]}),
    )
    assert len(conc.read_conclusions(_texts(10), client=client)) == 1


def test_una_sola_lamina_que_desborda_se_omite_sin_colgarse():
    """El corte por mitades tiene que terminar: una lámina ya no se parte más."""
    client = _FakeClient(_Response("{ truncado", stop_reason="max_tokens"))
    assert conc.read_conclusions(["una sola lámina"], client=client) == []


def test_un_rechazo_del_modelo_se_dice_no_se_traga():
    client = _FakeClient(_Response({"conclusions": []}, stop_reason="refusal"))
    with pytest.raises(RuntimeError):
        conc.read_conclusions(_texts(), client=client)


# ─────────────────────────── guardado ───────────────────────────

def test_guarda_resolviendo_marca_ola_y_metrica(db, engagement):
    found = [conc.Conclusion(
        claim="Focal mantiene el liderazgo como marca favorita.",
        page_number=19, kind="hallazgo", subjects=("Focal",),
        topic="Lugar favorito", metric_code="", direction="estable",
        wave_label="Ola 2", confident=True,
    )]
    resumen = conc.store_conclusions(db, str(engagement.id), found)
    db.flush()

    row = db.query(BrandConclusion).one()
    assert row.subject_slugs == ["focal"]
    assert row.metric_code == "favourite_place"
    assert row.wave_code == "w2"
    assert resumen["contrastables"] == 1


def test_una_afirmacion_sobre_varias_marcas_las_resuelve_todas(db, engagement):
    """«Little Caesars, KFC y Wendy's crecen» habla de tres marcas, no de una.

    Guardarla con un solo sujeto la dejaría sin resolver, y una conclusión sin resolver no
    se puede contrastar ni explicar — se perdería justo el tipo de frase más común.
    """
    found = [conc.Conclusion(
        claim="Focal y Rival muestran tendencia creciente.",
        page_number=13, kind="hallazgo", subjects=("Focal", "Rival"),
        topic="Lugar favorito", metric_code="", direction="sube",
        wave_label="", confident=True,
    )]
    conc.store_conclusions(db, str(engagement.id), found)
    db.flush()

    assert sorted(db.query(BrandConclusion).one().subject_slugs) == ["focal", "rival"]


def test_lo_que_no_resuelve_se_guarda_igual(db, engagement):
    """Sigue siendo una afirmación citable; simplemente no entra en el contraste."""
    found = [conc.Conclusion(
        claim="La categoría se mantiene plana en el trimestre.",
        page_number=8, kind="hallazgo", subjects=(),
        topic="tamaño de categoría", metric_code="", direction="estable",
        wave_label="", confident=True,
    )]
    resumen = conc.store_conclusions(db, str(engagement.id), found)
    db.flush()

    row = db.query(BrandConclusion).one()
    assert row.subject_slugs is None and row.metric_code is None
    assert resumen["guardadas"] == 1 and resumen["contrastables"] == 0


def test_releer_la_misma_entrega_reemplaza_no_duplica(db, engagement):
    """Un tracker se relee cuando se corrige; dos copias se explicarían dos veces."""
    def _one(claim: str):
        return [conc.Conclusion(claim=claim, page_number=19, kind="hallazgo",
                                subjects=("Focal",), topic="Lugar favorito",
                                metric_code="", direction="estable",
                                wave_label="", confident=True)]

    conc.store_conclusions(db, str(engagement.id), _one("Primera lectura del mazo."),
                           extraction_id="ext-1")
    db.flush()
    conc.store_conclusions(db, str(engagement.id), _one("Lectura corregida del mazo."),
                           extraction_id="ext-1")
    db.flush()

    rows = db.query(BrandConclusion).all()
    assert len(rows) == 1
    assert rows[0].claim == "Lectura corregida del mazo."


def test_otra_entrega_no_pisa_las_conclusiones_de_la_anterior(db, engagement):
    """Cada ola trae su mazo: la ola 3 no borra lo que concluyó la ola 2."""
    def _one(claim: str):
        return [conc.Conclusion(claim=claim, page_number=19, kind="hallazgo",
                                subjects=("Focal",), topic="Lugar favorito",
                                metric_code="", direction="estable",
                                wave_label="", confident=True)]

    conc.store_conclusions(db, str(engagement.id), _one("Lo que dijo la ola 2."),
                           extraction_id="ext-1")
    conc.store_conclusions(db, str(engagement.id), _one("Lo que dijo la ola 3."),
                           extraction_id="ext-2")
    db.flush()

    assert db.query(BrandConclusion).count() == 2


def test_borrar_el_encargo_se_lleva_sus_conclusiones(db, engagement):
    """Son datos privados de un cliente: no pueden sobrevivir al encargo."""
    from modules.brand_intel import service as svc

    conc.store_conclusions(db, str(engagement.id), [conc.Conclusion(
        claim="Focal mantiene el liderazgo como marca favorita.", page_number=19,
        kind="hallazgo", subjects=("Focal",), topic="Lugar favorito",
        metric_code="", direction="estable", wave_label="", confident=True,
    )])
    db.flush()

    svc.delete_engagement(db, engagement)
    assert db.query(BrandConclusion).count() == 0


def test_el_codigo_del_lector_manda_si_existe_en_el_diccionario(db, engagement):
    """El lector nombra el indicador con la frase delante; el guardado solo valida."""
    found = [conc.Conclusion(
        claim="Focal mejora su incidencia de consumo en la última medición.",
        page_number=14, kind="hallazgo", subjects=("Focal",),
        topic="incidencia de consumo",       # esta etiqueta NO calza con el diccionario
        metric_code="reach_7d",              # pero el lector sí supo nombrarla
        direction="sube", wave_label="", confident=True,
    )]
    conc.store_conclusions(db, str(engagement.id), found)
    db.flush()
    assert db.query(BrandConclusion).one().metric_code == "reach_7d"


def test_un_codigo_inventado_por_el_lector_no_se_guarda(db, engagement):
    """Un código fuera del diccionario partiría la serie igual que un typo en el Excel."""
    found = [conc.Conclusion(
        claim="Focal mejora su métrica inventada en la última medición.",
        page_number=14, kind="hallazgo", subjects=("Focal",),
        topic="algo rarísimo", metric_code="metric_que_no_existe",
        direction="sube", wave_label="", confident=True,
    )]
    conc.store_conclusions(db, str(engagement.id), found)
    db.flush()
    assert db.query(BrandConclusion).one().metric_code is None


def test_el_diccionario_viaja_en_el_prompt_cuando_se_da(db, engagement):
    from modules.brand_intel import service as svc

    class _Cap(_FakeClient):
        def __init__(self, *r: _Response) -> None:
            super().__init__(*r)
            self.systems: List[str] = []

        def create(self, **kwargs: Any) -> _Response:
            self.systems.append(kwargs["system"])
            return super().create(**kwargs)

    vocab = svc.vocabulary_for(db, str(engagement.id))
    client = _Cap(_Response({"conclusions": []}))
    conc.read_conclusions(_texts(3), client=client, vocab=vocab)

    assert "DICCIONARIO DE MÉTRICAS" in client.systems[0]
    assert "`favourite_place`" in client.systems[0]


# ── modo «solo conclusiones» ───────────────────────────────────────────


def test_conclusions_only_never_reads_a_slide_as_an_image(db, engagement, monkeypatch):
    """La propiedad que justifica el modo: con las cifras llegando por la plantilla del
    proveedor, leer cada lámina como imagen produce celdas que compiten con las suyas por
    la misma coordenada. El renderizador EXPLOTA si alguien lo llama."""
    from modules.brand_intel.ingest import jobs
    from modules.brand_intel.models.models import BrandExtractionCell

    def _explota(*a, **k):
        raise AssertionError("el modo solo-conclusiones NO puede leer láminas")

    monkeypatch.setattr("modules.brand_intel.ingest.pdf_vision.render_pages", _explota)
    monkeypatch.setattr("modules.brand_intel.ingest.pdf_vision.extract_page", _explota)
    monkeypatch.setattr("modules.brand_intel.ingest.pdf_vision.page_count",
                        lambda content: 65)
    monkeypatch.setattr("modules.brand_intel.ingest.discovery._page_texts",
                        lambda content: ["McDonald's lidera en satisfacción."] * 3)
    monkeypatch.setattr(
        "modules.brand_intel.ingest.conclusions.read_conclusions",
        lambda textos, vocab=None: [])
    monkeypatch.setattr(jobs, "_dispatch", lambda eid: None)
    monkeypatch.setattr("shared.database.session.SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    row = jobs.queue_extraction(db, engagement, b"%PDF", "mazo.pdf",
                                conclusions_only=True)
    assert bool(row.conclusions_only) is True

    out = jobs.run_extraction(str(row.id))
    assert out["status"] == "validated"
    db.refresh(row)
    assert int(row.pages_done) == 0
    assert "no se leyó ninguna lámina" in str(row.note)
    # y no dejó celdas compitiendo con las de la plantilla
    assert db.query(BrandExtractionCell).filter(
        BrandExtractionCell.extraction_id == row.id).count() == 0


def test_the_default_still_reads_the_slides(db, engagement, monkeypatch):
    """La otra mitad: sin la bandera, nada cambia. Un encargo del que todavía no tenemos
    plantilla del proveedor sigue necesitando la visión."""
    from modules.brand_intel.ingest import jobs

    monkeypatch.setattr("modules.brand_intel.ingest.pdf_vision.page_count",
                        lambda content: 3)
    monkeypatch.setattr(jobs, "_dispatch", lambda eid: None)
    row = jobs.queue_extraction(db, engagement, b"%PDF", "mazo.pdf")
    assert bool(row.conclusions_only) is False
