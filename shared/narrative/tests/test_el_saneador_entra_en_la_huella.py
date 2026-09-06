"""Cambiar una regla de SANEADO tiene que invalidar la caché de narrativas.

**El caso que lo obligó.** El 2026-09-06 se agregó al saneador la corrección del punto de
miles —«6.823.5», ilegible bajo la convención de casa, que es punto decimal—. Se desplegó, se
verificó el commit servido, se regeneró el boletín… y las ocho cifras seguían ahí.

El texto vino de la CACHÉ. Su clave hashea la pregunta (contexto, plantilla, modo, idioma) y
la receta (modelo, prompt de sistema, versión del guard), y el saneador no estaba en ninguna
de las dos — aunque post-procesa TODAS las narrativas.

La prueba de que era eso y no otra cosa está en el mismo PDF: §1 SÍ quedó arreglada en esa
misma corrida, porque a esa sección le habíamos cambiado el CONTEXTO —le agregamos la unidad
de cada indicador— y eso sí rota su clave. §2 no cambió ni de contexto ni de receta declarada,
y se sirvió intacta. Dos comportamientos distintos con una sola explicación.

`_recipe_fingerprint` existe justamente para cerrar esta familia: su propio comentario cuenta
tres antecedentes (`NO_META_COMMENTARY`, el veto de léxico visceral, `DIRECTION_DISCIPLINE`).
Éste es el cuarto, y entra por la puerta que faltaba.
"""
import hashlib
import pathlib

from shared.narrative import sanitize


def test_el_saneador_declara_su_huella():
    assert sanitize.FINGERPRINT
    esperada = hashlib.sha256(
        pathlib.Path(sanitize.__file__).read_bytes()).hexdigest()[:16]
    assert sanitize.FINGERPRINT == esperada, (
        "la huella dejó de derivarse del fuente del módulo: una constante que alguien tiene "
        "que acordarse de subir es exactamente lo que este mecanismo evita")


def test_la_huella_de_la_receta_INCLUYE_al_saneador(monkeypatch):
    """Si el saneador no entra en la clave, arreglar una regla de formato se despliega y no
    cambia nada: la caché sigue sirviendo el texto viejo."""
    from shared.narrative.claude_engine import NarrativeEngine

    motor = NarrativeEngine()
    antes = motor._recipe_fingerprint("boletin_sistema_pais", "deep", None, None)
    monkeypatch.setattr(sanitize, "FINGERPRINT", "otra-huella-distinta")
    despues = motor._recipe_fingerprint("boletin_sistema_pais", "deep", None, None)
    assert antes != despues, (
        "cambiar el saneador no rota la huella de la receta: un arreglo de formato quedaría "
        "sin efecto en silencio, que es exactamente lo que pasó con el punto de miles")


def test_tambien_rota_para_las_plantillas_del_cerebro(monkeypatch):
    """Las dos ramas de `_recipe_fingerprint` —cerebro y legacy— tienen que incluirlo. Un
    guard presente en un motor y ausente en el otro es el patrón que más se repite acá."""
    from shared.narrative.claude_engine import NarrativeEngine

    motor = NarrativeEngine()
    antes = motor._recipe_fingerprint("banking_summary", "deep", "banking", "comite_credito")
    monkeypatch.setattr(sanitize, "FINGERPRINT", "otra-huella-distinta")
    assert antes != motor._recipe_fingerprint(
        "banking_summary", "deep", "banking", "comite_credito")


def test_la_clave_de_cache_cambia_con_el_saneador(monkeypatch):
    """De punta a punta: es la clave, no la huella, lo que decide si se sirve texto viejo."""
    from shared.narrative.claude_engine import NarrativeEngine

    motor = NarrativeEngine()
    ctx = {"pais": "Chile", "series": []}
    antes = motor._cache_key(ctx, "boletin_sistema_pais", "deep", "es")
    monkeypatch.setattr(sanitize, "FINGERPRINT", "otra-huella-distinta")
    assert antes != motor._cache_key(ctx, "boletin_sistema_pais", "deep", "es")


def test_el_saneador_sigue_corrigiendo_el_punto_de_miles():
    """La regla cuyo despliegue no tuvo efecto. Sin ella, la huella no tiene qué proteger."""
    texto, cambios = sanitize.normalize_number_format("un total de 6.823.5 unidades")
    assert texto == "un total de 6,823.5 unidades"
    assert cambios
