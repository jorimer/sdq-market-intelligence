"""La fila del BVAR del 2026-09-05 declara su medida: `dlog_pct`

`d1e6f3a9c7b2` dejó a propósito en NULL la medida de las filas de `bvar_minnesota.*`, porque
ese mismo día el bloque cambió `pib_real` de variación TRIMESTRAL a INTERANUAL y `as_of` es
una fecha sin hora. Se determinó después, y no por parecido.

**Evidencia 1 — cronología.** La fila la escribió la cascada de `macro-canonical-sync` el
2026-09-05 a las **11:19:55 UTC** (`as_of` 2026-09-05; las dos emisiones manuales posteriores,
21:52 y 23:37 UTC, reportaron `skipped_duplicate: 1`, o sea que ya existía). El commit que
introduce la variación interanual (`0d5ce2d6`) se escribió a las **15:53:40 UTC** y se mergeó
a main a las **20:07:51 UTC**; el primer despliegue posterior fue ~20:30 UTC. La fila es
**cuatro horas y media anterior a que ese commit existiera**, y entre el despliegue y la
primera emisión manual no corrió ningún sync — el `last_run` del sync seguía siendo el de las
11:19:55. Se produjo con el bloque en `DLOG`.

**Evidencia 2 — la magnitud, reproducida sobre el dato real de producción.** Corriendo el
BVAR con las cinco series de prod en las dos medidas: la trimestral da 1,6892 para 2026-Q3
(trayectoria −0,87 · 1,69 · 1,14 · 1,08) y la interanual da 5,5672 (trayectoria 5,32 · 5,57 ·
5,37 · 5,11). El punto guardado es **0,7373**. Ninguna reproduce exacto —el dato se movió
desde entonces— pero la trayectoria interanual **no baja de 5,11** en ningún horizonte.
Sobre el observado, el QoQ del PIB promedia +1,13 % y el YoY +4,54 %.

**Por qué se puede estampar sin corromper el track record.** Porque en el mismo cambio la
MEDIDA entró en la clave del conjunto (`signals.backtest_id`). Sin eso, esta fila trimestral
y las interanuales del mismo modelo caían en el mismo `backtest_id` y su RMSE se promediaba:
medido sobre errores de 0,50 y 4,00 daba **2,850**, que no es el error de ninguno de los dos.
Ahora forma su propio conjunto de n=1 — no ancla, que es lo correcto porque el modelo
cambió, y no contamina al vigente.

El `where` está acotado a lo que se probó. `measure is null` ya implica «escrita antes de que
el arreglo se desplegara»; la cota de `as_of` está para que la afirmación quede verificable y
para que esta migración no diga nada sobre una fila que alguien inserte después.

Revision ID: a4c8e1b70d93
Revises: d1e6f3a9c7b2
"""
import sqlalchemy as sa
from alembic import op

revision = "a4c8e1b70d93"
down_revision = "d1e6f3a9c7b2"
branch_labels = None
depends_on = None

PIB_CODE = "bcrd.xls.pib_2018.serie_original_indice"
#: El último día en que el bloque del BVAR entregó el PIB en variación trimestral. El cambio
#: se mergeó a las 20:07 UTC de ese día y no hubo emisión entre el despliegue y el arreglo.
ULTIMO_DIA_TRIMESTRAL = "2026-09-05"

ESTAMPAR_MEDIDA = (
    "update mm_forecast_log set measure = 'dlog_pct' "
    "where measure is null "
    "  and model_id like 'bvar_minnesota.%' "
    "  and target_series = :pib "
    "  and as_of <= :corte"
)


def upgrade() -> None:
    op.execute(sa.text(ESTAMPAR_MEDIDA).bindparams(
        pib=PIB_CODE, corte=ULTIMO_DIA_TRIMESTRAL))


def downgrade() -> None:
    # No se revierte. Volver a poner NULL no restaura información: la borra. Lo que la fila
    # no registraba se determinó por cronología y por reproducción, y eso no se desanda con
    # un `update`.
    pass
