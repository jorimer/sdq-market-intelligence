"""La frescura se ancla al CORTE del informe, no al día en que se genera.

**El defecto, visto por el dueño en dos PDF del mismo período.** Uno decía «el dato más
reciente tiene 240 días» y el otro «150 días». El dato no había cambiado: `freshness_days` se
computa contra `date.today()`, así que la cifra envejecía sola dentro de un documento fechado.

En material que se manda a un tercero eso es peor que un número inútil: es un número que se
vuelve FALSO solo con esperar, en la sección que declara la metodología.

**Lo que dice ahora.** La fecha real del dato más reciente —`hoy − freshness_days`, que sí es
estable— comparada contra el corte. Si no hay observación posterior, el informe declara que su
dato es el del corte. Si la hay, lo DICE con cuántos días: que exista un corte más nuevo que el
pedido es información legítima, y callarlo dejaría creer que este es el último disponible.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pytest

from shared.products.report_sections import _fecha_del_corte, _frescura_md


class _Signals:
    """`DataHealth` mínimo: la frescura como días CONTRA HOY, que es como la emite el eje."""

    cadence = "quarterly"

    def __init__(self, fecha_del_dato: date, hoy: Optional[date] = None):
        self.freshness_days = ((hoy or date.today()) - fecha_del_dato).days


def test_el_MISMO_informe_dice_lo_mismo_UN_MES_DESPUES():
    """El corazón del defecto, probado como corresponde.

    Se generan dos veces el mismo informe —mismo dato, mismo corte— con un mes de diferencia
    en la fecha de generación. El texto tiene que ser IDÉNTICO. Antes cambiaba de «240 días» a
    «150 días» sin que nada del dato se hubiera movido.

    La primera versión de este test subía `freshness_days` sin mover el día, que es otra cosa
    —equivale a un dato más viejo, no a generarlo después— y fallaba con razón.
    """
    dato = date(2026, 3, 31)
    hoy = date(2026, 8, 27)
    un_mes_despues = date(2026, 9, 27)

    texto_hoy = _frescura_md(_Signals(dato, hoy), "2025", hoy=hoy)
    texto_despues = _frescura_md(_Signals(dato, un_mes_despues), "2025", hoy=un_mes_despues)
    assert texto_hoy == texto_despues
    assert "2026-03-31" in texto_hoy


def test_sin_observacion_posterior_declara_que_su_dato_es_el_del_corte():
    texto = _frescura_md(_Signals(date(2026, 3, 31)), "2026-03-31")
    assert "es el del corte" in texto
    assert "días después" not in texto


def test_con_observacion_posterior_lo_DICE_en_vez_de_callarlo():
    """Que exista un corte más nuevo que el pedido es información: callarlo dejaría creer
    que este informe es el último disponible."""
    texto = _frescura_md(_Signals(date(2026, 3, 31)), "2025")
    assert "2026-03-31" in texto and "90 días después" in texto
    assert "el corte manda" in texto


def test_sin_corte_se_conserva_la_lectura_de_PLATAFORMA():
    """Una vista no fechada pregunta otra cosa —«¿qué tan al día está el eje HOY?»— y ahí la
    antigüedad contra hoy es la respuesta correcta. El arreglo no puede romperla."""
    texto = _frescura_md(_Signals(date.today() - timedelta(days=5)), None)
    assert "tiene 5 días" in texto


def test_el_plural_se_concuerda():
    """«1 días» en un documento que se vende."""
    assert "un día." in _frescura_md(_Signals(date.today() - timedelta(days=1)), None)
    assert "menos de un día." in _frescura_md(_Signals(date.today()), None)


def test_sin_frescura_no_se_inventa_una():
    class _Sin:
        cadence = "quarterly"
        freshness_days = None

    texto = _frescura_md(_Sin(), "2025")
    assert "Frescura" not in texto and "Cadencia" in texto


@pytest.mark.parametrize("periodo,esperado", [
    ("2025", date(2025, 12, 31)),          # un producto anual pide su período como AÑO
    ("2025-06", date(2025, 6, 30)),        # fin de mes, incluido febrero y diciembre
    ("2025-12", date(2025, 12, 31)),
    ("2024-02", date(2024, 2, 29)),        # bisiesto: el 29 existe
    ("2025-09-30", date(2025, 9, 30)),
])
def test_el_corte_se_parsea_en_sus_TRES_formas(periodo, esperado):
    """Los dos productos de banca piden su período distinto —año y fecha— y los dos tienen
    que poder anclar. Un parser que solo entienda uno deja al otro con la cifra que deriva."""
    assert _fecha_del_corte(periodo) == esperado


def test_un_periodo_ilegible_no_rompe_el_informe():
    assert _fecha_del_corte("ultimo") is None
    assert "Cadencia" in _frescura_md(_Signals(date(2026, 3, 31)), "ultimo")
