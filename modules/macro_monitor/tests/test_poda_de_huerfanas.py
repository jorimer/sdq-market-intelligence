"""La poda de series huérfanas no puede correr ANTES de la sincronización.

`ingest_canonical` hace upsert y nunca poda: cuando una corrección del extractor renombra
una serie, el código viejo se queda sirviendo datos que ya nadie produce. Limpiarlo es
correcto — pero solo DESPUÉS de desplegar el código corregido y de que la sincronización
haya escrito los códigos nuevos.

Al revés, la poda borra observaciones que todavía se sirven y no repone nada; y con el
código viejo desplegado, la sincronización siguiente las repone con el nombre y el valor
equivocados. Es un error de ORDEN, del que no avisa ningún error: el `DELETE` funciona
perfectamente.

Medido contra producción el 2026-09-04: el motor corregido produce 2.096 series y el destino
—commit `e46dfbe`, código viejo— tiene 295 de ellas, el 14%. Correr la poda ahí habría
borrado 365 series y 26.135 observaciones.
"""
from modules.macro_monitor.service import huerfanas_podables, por_que_no_podar


def test_frena_cuando_el_destino_todavia_tiene_el_corpus_viejo():
    vivos = {f"nueva.{i}" for i in range(2096)}
    destino = {f"nueva.{i}" for i in range(295)} | {f"vieja.{i}" for i in range(365)}
    motivo = por_que_no_podar(vivos, destino)
    assert motivo, "dejó podar contra un destino que no recibió los códigos nuevos"
    assert "295" in motivo and "14%" in motivo


def test_deja_podar_cuando_la_sincronizacion_ya_escribio():
    vivos = {f"nueva.{i}" for i in range(2096)}
    destino = set(vivos) | {f"vieja.{i}" for i in range(365)}
    assert por_que_no_podar(vivos, destino) == ""


def test_un_motor_que_no_produjo_nada_no_autoriza_a_borrar_todo():
    """El caso que convierte una poda en un truncado: si la lectura del corpus falla y
    devuelve el conjunto vacío, TODO el destino queda huérfano."""
    assert por_que_no_podar(set(), {"a", "b"})


def test_no_poda_lo_que_la_sincronizacion_acaba_de_escribir():
    """El caso que costó descubrir: el modelo rotula la misma fila distinto en cada entorno.

    Producción escribió `…llegada_total.volumen.no_residentes` y el motor local, corriendo el
    mismo archivo, produjo `…llegada_total.total.no_residentes`. Comparando solo contra el
    motor local, esa serie recién escrita salía en la lista de borrado. Lo que la salva es
    que NO estaba antes de la sincronización.
    """
    antes = {"bcrd.xls.a.vieja", "bcrd.xls.a.otra_vieja"}
    destino = antes | {"bcrd.xls.a.nombre_que_puso_prod", "bcrd.xls.a.compartida"}
    motor = {"bcrd.xls.a.nombre_que_puso_el_motor_local", "bcrd.xls.a.compartida"}
    podables = huerfanas_podables(destino, motor, antes)
    assert podables == antes
    assert "bcrd.xls.a.nombre_que_puso_prod" not in podables


def test_solo_toca_las_series_del_motor_excel():
    antes = {"bcrd.xls.a.vieja", "fiscal_eo.ingresos", "remittances"}
    podables = huerfanas_podables(antes, set(), antes)
    assert podables == {"bcrd.xls.a.vieja"}


def test_lo_que_volvio_despues_de_podarlo_no_se_vuelve_a_podar():
    """Sin esto, la poda y la sincronización se pelean para siempre: una borra la serie y la
    otra la repone, cada mes. Que haya vuelto ES la prueba de que el motor del destino la
    produce — con otro nombre que el de este entorno."""
    antes = {"bcrd.xls.a.vieja", "bcrd.xls.bpagos.importaciones.nacionales"}
    destino = set(antes)
    motor = set()          # el motor local no produce ninguno de los dos nombres
    vivas = {"bcrd.xls.bpagos.importaciones.nacionales"}
    assert huerfanas_podables(destino, motor, antes, vivas_confirmadas=vivas) == {
        "bcrd.xls.a.vieja"}
