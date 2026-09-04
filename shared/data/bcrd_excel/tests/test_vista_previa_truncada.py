"""La vista previa que ve el modelo está truncada en columnas — y tiene que DECIRLO.

**El defecto.** `render_preview` muestra 12 columnas. Cuando la heurística no resuelve una
hoja y el trabajo cae en el modelo, éste ve 12 columnas de un cuadro de 34 y emite el rango
que ve: `value_col_end=11`. La serie sale con 10 de sus 32 trimestres y **se corta cinco años
antes**, sin error ni marca. Pasó con `PIB$_Trim_Acum` del PIB por sector de origen, que
terminaba en 2020-Q2 mientras sus tres hojas hermanas llegaban a 2025-Q4.

No se arregla ensanchando la vista: de las 27 planillas canónicas, **21 pasan de 12 columnas**
y una llega a 256. Se arregla diciéndole al modelo que lo que ve está cortado y que, si el
patrón sigue, deje el fin del rango ABIERTO — el extractor ya interpreta `None` como «hasta el
final de la hoja».

Es la misma familia que el nombrado por lotes: el modelo contestaba bien sobre lo que se le
mostraba, y lo que se le mostraba era incompleto sin que nada lo declarara.
"""
from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.interpreter import render_preview
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import Grid, Workbook


def _ancha(ncols=34):
    filas = [["AÑOS"] + [2018 if c == 1 else None for c in range(1, ncols)],
             [None] + ["E-M"] * (ncols - 1),
             ["Agropecuario"] + [1.0] * (ncols - 1)]
    return Grid(name="H", rows=filas)


def test_la_vista_previa_declara_que_esta_cortada():
    texto = render_preview(_ancha(34), cols=12)
    assert "34" in texto.splitlines()[0], "la vista no declara el ancho real"
    assert "truncad" in texto.lower() or "no se muestran" in texto.lower(), (
        "la vista previa corta las columnas sin decirlo: el modelo contesta el rango que ve "
        f"y la serie se corta. Vista:\n{texto[:300]}")


def test_una_hoja_angosta_no_dice_nada_de_truncamiento():
    """Sin corte no hay aviso: un texto que siempre advierte deja de ser una advertencia."""
    texto = render_preview(_ancha(6), cols=12)
    assert "truncad" not in texto.lower()


def test_un_rango_ABIERTO_lee_hasta_el_final_de_la_hoja():
    """La salida que la vista habilita: `value_col_end=None` significa hasta el final, y el
    extractor ya lo respeta. Sin esto, decirle al modelo que deje el rango abierto no
    serviría de nada."""
    grid = _ancha(34)
    spec = ExtractionSpec(
        file="f", sheet="H", orientation="matrix", data_row_start=2,
        period_header_row=0, subperiod_header_row=1, label_col=0,
        value_col_start=1, value_col_end=None, code_prefix="p",
    )
    recs = extract_records(Workbook(path=None, grids=[grid]), spec)
    assert len(recs) == 33, f"leyó {len(recs)} columnas de 33"
