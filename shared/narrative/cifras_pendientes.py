"""Cifras sin respaldo que SOBREVIVEN a la reparación, del motor a quien publica.

Hermana de ``relaciones_pendientes`` y con la misma mecánica (ver ``hallazgos_pendientes``),
pero es un hallazgo distinto y por eso un canal distinto: una relación invertida hace que el
documento se contradiga; una cifra sin respaldo hace que el documento afirme un número que
nadie puede sostener. El caso que la motiva llegó a un PDF de rating REAL con `guard_flags=1`,
porque la marca no tenía ningún consumidor.

**Lo que este canal reemplaza.** Las tres superficies de entrega volvían a juzgar el texto por
su cuenta, con el snapshot en la mano en vez del contexto que lo generó. Eso vetaba prosa
correcta: el «132 %» de un Deep Dive de Asociación Bonao era la razón 1,32 servida, el motor
la vio y no marcó nada, y el ensamblador la marcó porque su contexto no la tenía. Detalle
completo en ``hallazgos_pendientes``.
"""
from __future__ import annotations

from shared.narrative.hallazgos_pendientes import CanalDeHallazgos

_CANAL = CanalDeHallazgos("cifras")

acumulando = _CANAL.acumulando
registrar = _CANAL.registrar
pendientes = _CANAL.pendientes
asegurando = _CANAL.asegurando
