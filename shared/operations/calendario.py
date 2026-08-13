"""Cadencia anclada al CALENDARIO DE PUBLICACIÓN de la fuente, no al reloj.

**El defecto que esto corrige.** El scheduler computaba ``next_run_at = ahora + interval_hours``.
Para una fuente trimestral eso significa "90 días desde que se corrió por última vez", y la
ventana se desfasa sola: ``dga-trade-sync`` corrió el 2026-06-27 —tres días antes de que
cerrara Q2— así que su próxima corrida quedó fijada para el 2026-09-25. La DGA publicó
2026-Q2 en el medio y el sistema siguió sirviendo 2026-Q1 en informes fechados en agosto, con
casi tres meses de retraso y sin decirlo.

Un intervalo relativo responde "¿cuánto hace que corrí?". La pregunta correcta es "¿hay un
período nuevo publicado?". Esto computa lo segundo: el próximo disparo cae poco después del
cierre del período siguiente, más el rezago con que la fuente suele publicar.

No reemplaza al intervalo: las operaciones sin ancla declarada siguen con su cadencia
relativa, que para un feed continuo (macro diario, caché tibia) es lo correcto.
"""
from datetime import datetime, timedelta
from typing import Optional

# Rezago típico entre el cierre del período y su publicación. Conservador a propósito: si se
# dispara antes de que la fuente publique, el sync no encuentra nada nuevo y el próximo
# disparo vuelve a caer recién el período siguiente — se pierde el trimestre entero. Mejor
# esperar de más y reintentar seguido (ver REINTENTO_DIAS).
REZAGO_PUBLICACION_DIAS = {"trimestral": 45, "anual": 90}

# Cuando ya pasó el rezago pero la fuente todavía no publicó, se reintenta con esta cadencia
# en vez de esperar al período siguiente. Es la diferencia entre "llego tarde una semana" y
# "me pierdo el trimestre".
REINTENTO_DIAS = 7

ANCLAJES = ("trimestral", "anual")


def _trimestre(d: datetime) -> tuple:
    """``(año, trimestre)`` del instante dado."""
    return (d.year, (d.month - 1) // 3 + 1)


def _cierre(yq: tuple) -> datetime:
    """Último instante del trimestre ``(año, q)``."""
    año, q = yq
    fin_mes = q * 3
    if fin_mes == 12:
        return datetime(año, 12, 31)
    return datetime(año, fin_mes + 1, 1) - timedelta(days=1)


def _anterior(yq: tuple) -> tuple:
    año, q = yq
    return (año - 1, 4) if q == 1 else (año, q - 1)


def _siguiente(yq: tuple) -> tuple:
    año, q = yq
    return (año + 1, 1) if q == 4 else (año, q + 1)


def periodo_esperado(anclaje: str, ahora: datetime) -> Optional[str]:
    """El último período que la fuente YA debería haber publicado, o None.

    >>> periodo_esperado("trimestral", datetime(2026, 8, 20))
    '2026-Q2'
    >>> periodo_esperado("trimestral", datetime(2026, 7, 10))
    '2026-Q1'
    """
    if anclaje not in ANCLAJES:
        return None
    rezago = timedelta(days=REZAGO_PUBLICACION_DIAS[anclaje])
    if anclaje == "anual":
        año = ahora.year - 1
        if datetime(año, 12, 31) + rezago > ahora:
            año -= 1
        return str(año)
    yq = _trimestre(ahora)
    for _ in range(8):
        if _cierre(yq) + rezago <= ahora:
            return f"{yq[0]}-Q{yq[1]}"
        yq = _anterior(yq)
    return None


def proximo_disparo(anclaje: Optional[str], ahora: datetime,
                    intervalo_horas: int,
                    ultimo_periodo_visto: Optional[str] = None) -> datetime:
    """Cuándo debe correr la próxima vez.

    Sin *anclaje* se conserva la cadencia relativa de siempre — para un feed continuo
    (macro diario, caché tibia) es lo correcto.

    Con anclaje, apunta al cierre del próximo período más el rezago de publicación. Y si
    *ultimo_periodo_visto* muestra que ya vamos ATRASADOS respecto de lo que la fuente
    debería haber publicado, reintenta pronto en vez de esperar al período siguiente: así
    fue exactamente como se perdió 2026-Q2 entero.

    >>> proximo_disparo("trimestral", datetime(2026, 6, 27), 2160).date().isoformat()
    '2026-08-14'
    >>> (datetime(2026, 6, 27) + timedelta(hours=2160)).date().isoformat()  # la relativa
    '2026-09-25'
    >>> # En agosto con Q1 cargado y Q2 ya publicado: no espera a noviembre.
    >>> proximo_disparo("trimestral", datetime(2026, 8, 20), 2160, "2026-Q1").date().isoformat()
    '2026-08-27'
    """
    if anclaje not in ANCLAJES:
        return ahora + timedelta(hours=intervalo_horas)

    esperado = periodo_esperado(anclaje, ahora)
    if ultimo_periodo_visto and esperado and str(ultimo_periodo_visto) < esperado:
        return ahora + timedelta(days=REINTENTO_DIAS)

    rezago = timedelta(days=REZAGO_PUBLICACION_DIAS[anclaje])
    if anclaje == "anual":
        objetivo = datetime(ahora.year, 12, 31) + rezago
        return objetivo if objetivo > ahora else datetime(ahora.year + 1, 12, 31) + rezago
    yq = _trimestre(ahora)
    objetivo = _cierre(yq) + rezago
    return objetivo if objetivo > ahora else _cierre(_siguiente(yq)) + rezago
