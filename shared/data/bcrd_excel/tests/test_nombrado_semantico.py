"""El nombrado semántico no puede devolver dos veces el mismo nombre.

Con una ventana de contexto corta el modelo devolvía el MISMO nombre para filas
distintas —no por incapacidad, sino porque no veía el encabezado de bloque que las
separa, decenas de filas más arriba—. Aceptar ese nombre fusionaría dos series
diferentes, que es peor que un nombre feo.
"""
from shared.data.bcrd_excel.interpreter import name_ambiguous_rows
from shared.data.bcrd_excel.workbook import Grid


class _FakeBlock:
    def __init__(self, payload):
        self.type = "tool_use"
        self.input = payload


class _FakeResponse:
    def __init__(self, payload):
        self.content = [_FakeBlock(payload)]


class _FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_prompt = ""

    def create(self, **kw):
        self.last_prompt = kw["messages"][0]["content"]
        return _FakeResponse(self._payload)


class _FakeClient:
    def __init__(self, payload):
        self.messages = _FakeMessages(payload)


def _grid():
    rows = [["ACTIVOS"], ["Otros"], ["PASIVOS"], ["Otros"]]
    return Grid(name="H", rows=rows)


def test_duplicate_names_are_rejected_never_merged():
    client = _FakeClient({"names": [
        {"row": 1, "name": "Activos > Otros"},
        {"row": 3, "name": "Activos > Otros"},      # el modelo repitió
    ]})
    out = name_ambiguous_rows(_grid(), [1, 3], client=client, model="m")
    assert list(out) == [1]          # la segunda se descarta, no se fusiona
    assert out[1] == "Activos > Otros"


def test_distinct_names_are_all_kept():
    client = _FakeClient({"names": [
        {"row": 1, "name": "Activos > Otros"},
        {"row": 3, "name": "Pasivos > Otros"},
    ]})
    out = name_ambiguous_rows(_grid(), [1, 3], client=client, model="m")
    assert out == {1: "Activos > Otros", 3: "Pasivos > Otros"}


def test_the_prompt_demands_distinct_names():
    """La regla va EN el prompt: pedirla es lo que hizo que dejara de repetir."""
    client = _FakeClient({"names": []})
    name_ambiguous_rows(_grid(), [1, 3], client=client, model="m")
    assert "DISTINTOS ENTRE SÍ" in client.messages.last_prompt


def test_rows_outside_the_request_are_ignored():
    client = _FakeClient({"names": [{"row": 99, "name": "Inventado"}]})
    assert name_ambiguous_rows(_grid(), [1], client=client, model="m") == {}


def test_no_ambiguous_rows_means_no_model_call():
    """Sin ambigüedad no se gasta una llamada."""
    class _Explode:
        class messages:
            @staticmethod
            def create(**kw):
                raise AssertionError("no debió llamar al modelo")
    assert name_ambiguous_rows(_grid(), [], client=_Explode()) == {}
