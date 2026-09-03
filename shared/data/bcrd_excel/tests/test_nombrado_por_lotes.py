"""Muchas filas ambiguas de una vez: la respuesta se trunca y NO se nombra ninguna.

**El defecto real.** El PIB por origen (`pib_origen_2018.xlsx`) repite cada sector en tres
bloques —nivel, tasa de crecimiento, incidencia—, así que sus dos hojas de volumen encadenado
llegan con **64 filas ambiguas** cada una. La petición de nombres tenía `max_tokens=2000`:
64 nombres jerárquicos largos no entran, la respuesta se cortaba a mitad del bloque de
herramienta y se parseaba a **cero nombres**. El log lo decía —«Claude nombró 0 de 64 filas
ambiguas»— en nivel INFO, se pagaban US$0,11 por las dos hojas, y las 128 series quedaban con
el número de fila como nombre. Las hojas hermanas (`PIB$_Trim`, 32 filas) sí entraban: por eso
el mismo archivo tenía la mitad de sus series bien nombradas y la otra mitad no.

Que el tamaño del pedido decida en silencio si el nombrado ocurre es lo que se cierra acá: se
pide POR LOTES, cada uno dentro del presupuesto.
"""
from shared.data.bcrd_excel.interpreter import name_ambiguous_rows
from shared.data.bcrd_excel.workbook import Grid

TOPE_REAL = 24   # cuántos nombres entran de verdad en una respuesta


def _filas_pedidas(prompt: str):
    """Las filas marcadas en el prompt. Solo las líneas de DATOS: el texto de instrucciones
    también menciona '<<< NOMBRAR' y colarlo rompe el doble."""
    return [int(ln.split()[1].rstrip(":")) for ln in prompt.splitlines()
            if ln.startswith("fila ") and "<<< NOMBRAR" in ln]


class _FakeBlock:
    def __init__(self, payload):
        self.type = "tool_use"
        self.input = payload


class _FakeResponse:
    def __init__(self, payload):
        self.content = [_FakeBlock(payload)]
        self.usage = None


class _MessagesQueTrunca:
    """Emula el tope de salida: más de `TOPE_REAL` nombres y la respuesta llega cortada,
    que es lo que el parser ve como CERO nombres."""

    def __init__(self):
        self.llamadas = 0

    def create(self, **kw):
        self.llamadas += 1
        prompt = kw["messages"][0]["content"]
        pedidas = _filas_pedidas(prompt)
        if len(pedidas) > TOPE_REAL:
            return _FakeResponse({})          # truncada: el bloque no trae `names`
        return _FakeResponse({"names": [{"row": r, "name": f"Bloque > Sector {r}"}
                                        for r in pedidas]})


class _ClienteQueTrunca:
    def __init__(self):
        self.messages = _MessagesQueTrunca()


def _grid(n):
    return Grid(name="PIBK_Trim", rows=[[f"Sector {i}"] for i in range(n + 5)])


def test_sesenta_y_cuatro_filas_se_nombran_igual():
    """El caso exacto del PIB por origen: 64 filas ambiguas en una hoja."""
    filas = list(range(1, 65))
    cliente = _ClienteQueTrunca()
    out = name_ambiguous_rows(_grid(70), filas, client=cliente, model="m")
    assert len(out) == 64, f"se nombraron {len(out)} de 64"
    assert cliente.messages.llamadas > 1, "no se dividió el pedido en lotes"


def test_pocas_filas_siguen_yendo_en_una_sola_llamada():
    """Lo que ya funcionaba no se encarece: 32 filas entran en un pedido."""
    cliente = _ClienteQueTrunca()
    out = name_ambiguous_rows(_grid(40), list(range(1, 25)), client=cliente, model="m")
    assert len(out) == 24
    assert cliente.messages.llamadas == 1


def test_los_nombres_siguen_siendo_UNICOS_entre_lotes():
    """La regla de no fusionar dos series vale para todo el pedido, no por lote: si el
    modelo repite un nombre en el lote 3 que ya usó en el 1, se descarta igual."""
    class _Repite(_MessagesQueTrunca):
        def create(self, **kw):
            self.llamadas += 1
            prompt = kw["messages"][0]["content"]
            pedidas = _filas_pedidas(prompt)
            return _FakeResponse({"names": [{"row": r, "name": "Siempre El Mismo"}
                                            for r in pedidas]})

    cliente = _ClienteQueTrunca()
    cliente.messages = _Repite()
    out = name_ambiguous_rows(_grid(70), list(range(1, 65)), client=cliente, model="m")
    assert len(out) == 1, f"se aceptaron {len(out)} nombres repetidos"
