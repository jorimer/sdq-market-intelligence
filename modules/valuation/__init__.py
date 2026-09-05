"""Eje `valuation` — cuánto vale una entidad, no qué tan sana está.

La distinción es el eje entero. `banking_score` responde lo segundo —Perfil SDQ, propensión
a quiebra, alertas tempranas— y **ninguna de esas salidas se convierte en un valor**: un
score alto describe solidez, no precio, y tratarlo como proxy de valor sería inventar una
equivalencia que nadie midió.

El método es **Excess Return** (residual income): una entidad vale su libro más el valor
presente de lo que gane POR ENCIMA de lo que su capital exige. De ahí sale la lectura que
importa —`ROE − Ke`— y de ahí sale que una entidad rentable pueda estar destruyendo valor.

La estructura sigue el plan del BLOQUE VL:

* ``engine/`` — costo de capital (T-VL-3), excess return y terminal (T-VL-4), regresión P/B
  (T-VL-6). Dos motores independientes que dan UN rango; si divergen, la divergencia **es
  información** y se reporta, no se promedia.
* ``panel/`` — comparables LATAM (T-VL-6) y transacciones RD/Caribe (T-VL-7). La vista de
  M&A queda cerrada hasta que el panel llegue a N ≥ 8 con precio sobre valor libro
  verificable.
* ``models/`` — persistencia de supuestos y corridas.
* ``api/`` — la superficie HTTP del eje.
"""
