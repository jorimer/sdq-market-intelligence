"""Relaciones invertidas que SOBREVIVEN a la reparación, desde el motor hasta quien publica.

**El problema que resuelve.** El motor de narrativa detecta una comparación invertida, le pide
al modelo que la corrija y —desde 2026-08-24— le entrega la lectura correcta ya redactada para
que la copie. Si aun así el texto la contradice, hasta entonces el hallazgo moría ahí: se
escribía una línea de log y el informe se entregaba igual. Así salió publicada la §7 de un
Deep Dive de banca, afirmando que la capitalización contable «supera» al promedio de su grupo
cuando estaba por debajo, y contradiciendo a la §2 y a la §10 del mismo documento.

La mecánica —y por qué hace falta un canal en vez del valor de retorno— vive en
``shared/narrative/hallazgos_pendientes``. Acá solo se nombra el canal: la política (premium
veta, Pulse solo registra) la decide quien conoce el nivel, no el motor, que es transversal a
los diez ejes.
"""
from __future__ import annotations

from shared.narrative.hallazgos_pendientes import CanalDeHallazgos

_CANAL = CanalDeHallazgos("relaciones")

acumulando = _CANAL.acumulando
registrar = _CANAL.registrar
pendientes = _CANAL.pendientes
asegurando = _CANAL.asegurando
