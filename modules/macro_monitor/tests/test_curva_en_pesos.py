"""La curva soberana en pesos — el insumo del costo de capital, y su escala.

**De dónde salió.** El valuador necesita una tasa libre de riesgo LARGA en pesos, y no la
teníamos: la TPM es overnight, está en 5,25 % contra una inflación de 5,47 %, y usarla a diez
años daría una tasa real NEGATIVA — con eso el modelo diría que casi cualquier entidad crea
valor. Buscando la fuente apareció que ya estaba en el catálogo del BCRD: el cuadro V.1
«Valores subastados del Banco Central en moneda nacional», con seis plazos y 285 meses.

El término largo es **9,78 %**, no 5,25 %. Usar la TPM habría subestimado `Ke` en **453
puntos básicos**, que a un ROE típico de 13 % es la diferencia entre crear y destruir valor
en casi todo el sistema.

**La escala, y el defecto que casi se cuela.** El archivo guarda fracciones. La corrección se
declara por PREFIJO de serie, y el prefijo natural —`…valores_bc_mn.tasa`— **deja fuera los
dos plazos largos**: al extraerse pierden el rótulo del super-encabezado y quedan como
`de_1_a_2_anos` y `mas_de_dos_anos`. O sea que la corrección habría fallado exactamente en
las dos series que el costo de capital necesita, en silencio, dejando un 0,0978 donde va un
9,78. Se nombran una por una.

**Y por qué NO se ensancha el prefijo al archivo entero:** el mismo cuadro trae los MONTOS
subastados, que son miles de millones. El tope de 1,5 los protege por el TAMAÑO del valor, no
por lo que la serie ES — un monto de cero o de un peso caería adentro y se multiplicaría por
cien sin que nada falle.
"""
import pytest

from shared.data.bcrd_excel.canonical import ESCALAS_CURADAS, escala_curada

_P = "bcrd.xls.valores_bc_mn."

#: La curva medida en 2026, en fracción tal como la guarda el archivo, y en por-ciento.
CURVA = [
    ("tasa_de_interes_de_1_a_30_dias", 0.0700, 7.00),
    ("tasa_de_interes_de_31_a_90_dias", 0.0720, 7.20),
    ("tasa_de_interes_de_91_a_180_dias", 0.0812, 8.12),
    ("tasa_de_interes_de_181_a_360_dias", 0.0870, 8.70),
    ("de_1_a_2_anos", 0.0874, 8.74),
    ("mas_de_dos_anos", 0.0978, 9.78),
]


@pytest.mark.parametrize("serie,fraccion,por_ciento", CURVA)
def test_cada_plazo_de_la_curva_se_corrige(serie, fraccion, por_ciento):
    assert escala_curada(_P + serie, fraccion) == pytest.approx(por_ciento, abs=1e-9)


@pytest.mark.parametrize("serie,_f,por_ciento", CURVA)
def test_la_correccion_es_idempotente(serie, _f, por_ciento):
    """El tope es lo que distingue una corrección de una multiplicación ciega: si el BCRD
    republica en por-ciento, no se vuelve a multiplicar."""
    assert escala_curada(_P + serie, por_ciento) == pytest.approx(por_ciento, abs=1e-9)


def test_los_DOS_plazos_largos_estan_nombrados_uno_por_uno():
    """El defecto que casi se cuela. Un prefijo `…tasa` los deja afuera porque al extraerse
    pierden el rótulo del super-encabezado."""
    for serie in ("de_1_a_2_anos", "mas_de_dos_anos"):
        assert _P + serie in ESCALAS_CURADAS, (
            f"{serie} no tiene escala curada: se persistiría como 0,09 en vez de 9 %, "
            "y es justo el plazo que el costo de capital necesita")


def test_los_MONTOS_no_se_multiplican():
    """El otro lado: ensanchar el prefijo al archivo pondría los montos bajo la misma regla."""
    for monto in (43_663_820_000.0, 2_000_000_000.0, 0.0, 1.0):
        assert escala_curada(_P + "montos_de_91_a_180_dias", monto) == monto


def test_la_curva_queda_CRECIENTE_al_corregir():
    """La verificación de sentido. Una curva de plazos que no crece es una señal de que la
    escala o el mapeo están mal — y a ×100 esta queda 7,00 → 9,78, monótona."""
    valores = [escala_curada(_P + s, f) for s, f, _ in CURVA]
    assert valores == sorted(valores), f"la curva no es creciente: {valores}"
    assert valores[-1] > valores[0] + 2.0, "el término largo no está por encima del corto"


def test_el_termino_largo_supera_a_la_TPM_y_a_la_inflacion():
    """La razón por la que este archivo existe para el valuador: la TPM (5,25 %) está por
    DEBAJO de la inflación (5,47 %), y usarla como libre de riesgo a diez años daría una tasa
    real negativa."""
    largo = escala_curada(_P + "mas_de_dos_anos", 0.0978)
    assert largo > 5.25, "el término largo no supera a la TPM"
    assert largo > 5.47, "el término largo no supera a la inflación vigente"
    assert largo - 5.25 > 4.0, (
        "la brecha contra la TPM se achicó por debajo de los 400 pb; el hallazgo que "
        "justifica ingerir esta curva era que la brecha son ~453 pb")
