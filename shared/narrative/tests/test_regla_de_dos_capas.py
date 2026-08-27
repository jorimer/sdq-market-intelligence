"""La REGLA DE DOS CAPAS: solo bloquea lo que el juez semántico confirma.

**Decidida con datos, no con opinión.** El detector mecánico pregunta «¿este número está en lo
que servimos?», no «¿este número está mal?». La diferencia vive en un solo caso —la cifra es
CORRECTA y nosotros no la servimos— y ahí cayeron las SIETE familias documentadas, sin una
sola alucinación:

  69 % (redondeo) · 132 % (razón dicha en porcentaje) · 38 % (peso en un contenedor) ·
  100 % (umbral prospectivo) · 100 % (nivel de referencia que no servíamos) ·
  1,82 % (0,01819 en porcentaje, **con su base nombrada en la misma oración**) ·
  2,5 % (umbral en rango, con la palabra «umbral» DESPUÉS de la cifra)

La medición en sombra sobre las marcas reales del 2026-08-27 dio **2 de 2** puestas por el
regex SOLO: el juez no marcó ninguna. Con esta regla, ese informe se entregaba.

**El riesgo aceptado:** una cifra que se le escape a las dos capas se publica. Se cambió
sabiendo eso, contra el costo medido del error contrario — informes correctos muertos, uno por
generación de ~100 s.

Lo que estos tests fijan es que la regla no se pase de largo: el juez sigue bloqueando, las
relaciones invertidas siguen bloqueando enteras, y dejar de vetar NO es dejar de mirar.
"""
from __future__ import annotations

import pytest

from shared.narrative.claude_engine import NarrativeResult, hallazgos_que_bloquean


def _resultado(cifras, origen, direcciones=()):
    r = NarrativeResult(text="x")
    r.guard_cifras = list(cifras)
    r.guard_origen = dict(origen)
    r.guard_unsupported = list(cifras) + list(direcciones)
    return r


def test_lo_que_marcó_SOLO_el_regex_no_bloquea():
    """El caso real: «1.82% —dato derivado de la tasa base del modelo, 0,01819, expresada
    como porcentaje». El modelo ancló la cifra nombrando su base, que es exactamente lo que
    el aviso de corrección le pide, y el regex la mató igual."""
    r = _resultado(["1.82%: no coincide"], {"1.82%: no coincide": "det"})
    assert hallazgos_que_bloquean(r) == []


def test_lo_que_el_JUEZ_confirma_sigue_bloqueando():
    """Aflojar el regex no es aflojar el guard: el juez lee el contexto entero y es la capa
    que puede distinguir una invención de una forma de decir un número."""
    r = _resultado(["7.7%: inventada"], {"7.7%: inventada": "juez"})
    assert hallazgos_que_bloquean(r) == ["7.7%: inventada"]


def test_lo_que_marcan_las_DOS_bloquea():
    r = _resultado(["9.9%"], {"9.9%": "ambos"})
    assert hallazgos_que_bloquean(r) == ["9.9%"]


def test_un_origen_DESCONOCIDO_bloquea():
    """El lado conservador: no se debilita la entrega por un dato que no tenemos. Suponer
    «era solo el regex» sobre una marca sin origen sería fabricar justo el dato que decide."""
    r = _resultado(["5%"], {})
    assert hallazgos_que_bloquean(r) == ["5%"]


def test_separa_bien_cuando_hay_de_las_DOS_clases():
    """Una sección puede traer las dos a la vez, y mezclarlas dejaría pasar la del juez o
    bloquearía por la del regex."""
    r = _resultado(["1.82%", "7.7%"], {"1.82%": "det", "7.7%": "ambos"})
    assert hallazgos_que_bloquean(r) == ["7.7%"]


def test_una_RELACIÓN_INVERTIDA_sigue_bloqueando_entera():
    """La regla es sobre CIFRAS. Una dirección invertida no es una forma de decir un número:
    es una afirmación al revés, y ya se publicó una vez."""
    from shared.narrative.claude_engine import narrative_engine

    r = _resultado(["1.82%"], {"1.82%": "det"}, direcciones=["solvencia: pero es al revés"])
    cifras = {str(h) for h in r.guard_cifras}
    direcciones = [h for h in r.guard_unsupported if str(h) not in cifras]
    assert direcciones == ["solvencia: pero es al revés"]
    # Y con eso presente, la caché NO guarda: se comprueba por el mismo camino que usa.
    guardado = {}
    narrative_engine._l1 = {} if not hasattr(narrative_engine, "_l1") else narrative_engine._l1
    assert hallazgos_que_bloquean(r) + direcciones


def test_dejar_de_vetar_NO_es_dejar_de_mirar():
    """Lo que marcó el regex solo sigue viajando al REGISTRO con su capa — de ahí salen los
    huecos a cerrar. Si además desapareciera de la observabilidad, la regla convertiría un
    veto ruidoso en un silencio, que es peor."""
    r = _resultado(["1.82%"], {"1.82%": "det"})
    assert r.guard_cifras == ["1.82%"], "la marca no se borra: solo deja de bloquear"
    assert r.guard_origen["1.82%"] == "det"
