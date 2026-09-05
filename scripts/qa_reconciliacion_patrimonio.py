"""QA: reconcilia PATRIMONIO y UTILIDAD por entidad contra el estado publicado por la SB.

Es el sensor de T-VL-1, y existe porque el eje de valuación se construye sobre estas dos
cifras. Un valuador que multiplica un patrimonio equivocado por un múltiplo correcto entrega
una valuación equivocada con toda la apariencia de estar bien — el modo de falla más caro que
tiene ese producto.

**Por qué contra SIMBAD y no contra nuestra propia fuente.** SIMBAD es el Superset PÚBLICO de
la Superintendencia: el mismo dato que ingerimos, publicado por el emisor y consultable sin
credencial. Comparar la ingesta contra la API que la alimenta no probaría nada — probaría que
copiamos bien lo que ya copiamos. Contra el estado publicado sí: caza el error de MAPEO, que
es el que sobrevive a un ETL que "corre bien".

**Por entidad, no por total.** `qa_simbad_crosscheck.py` compara totales por tipo, y un total
puede cerrar con dos entidades cruzadas entre sí. La valuación es por entidad; la
reconciliación también.

Lectura del veredicto: la razón nuestro/publicado ≈ 1,00. La tolerancia es del 1 %, más
estrecha que el 5 % del crosscheck de totales, porque acá no hay agregación que promedie
ruido — es la misma cifra en los dos lados o no lo es.

Uso (prod, solo lectura):
    DATABASE_URL="..." python scripts/qa_reconciliacion_patrimonio.py --year 2025 --month 12

Sale con código distinto de cero si alguna entidad queda fuera de tolerancia, así que sirve
de sensor post-sync.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from shared.data.simbad_client import (  # noqa: E402
    DATASET_BALANCE,
    DATASET_INCOME,
    _post_chart_data,
)
from shared.database.session import engine  # noqa: E402

#: Cómo nombra SIMBAD a cada entidad frente a cómo la nombramos nosotros. Se declara y no se
#: adivina con similitud de cadenas: un emparejador difuso que acierta el 95 % de las veces
#: falla en la entidad grande justo cuando importa, y el error se ve como una discrepancia
#: de dato en vez de como lo que es.
EQUIVALENCIAS = {
    "POPULAR": "Banco Popular Dominicano",
    "BANRESERVAS": "Banco de Reservas de la República Dominicana",
    "BHD": "Banco Múltiple BHD",
    "SCOTIABANK": "Scotiabank",
    "SANTA CRUZ": "Banco Múltiple Santa Cruz",
}
#: El sensor exige AL MENOS tres. Menos que eso no distingue un mapeo correcto de una
#: coincidencia.
MINIMO_DE_ENTIDADES = 3
TOLERANCIA = 0.01

_DIA = {3: 31, 6: 30, 9: 30, 12: 31}
_FILTROS_TIPO = [
    {"col": "SISTEMA", "op": "==", "val": "FINANCIERO"},
    {"col": "TIPO_DE_ENTIDAD", "op": "==", "val": "BANCOS MÚLTIPLES"},
    {"col": "CONCEPTO_NIVEL_2", "op": "==", "val": "TODOS"},
    {"col": "CONCEPTO_NIVEL_3", "op": "==", "val": "TODOS"},
]


def _publicado(dataset: int, concepto: str, year: int, month: int) -> dict:
    """``{ENTIDAD: monto}`` de un concepto, tal como lo publica la SB."""
    filas = _post_chart_data(
        dataset, ["ENTIDAD", "MONTO"],
        [{"col": "Año", "op": "==", "val": year},
         {"col": "Mes", "op": "==", "val": month},
         {"col": "CONCEPTO_NIVEL_1", "op": "==", "val": concepto},
         *_FILTROS_TIPO], row_limit=100,
    )
    return {f["ENTIDAD"]: float(f["MONTO"]) for f in filas
            if f.get("ENTIDAD") != "TODOS" and f.get("MONTO") is not None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--month", type=int, choices=(3, 6, 9, 12), default=12)
    args = ap.parse_args()
    period_end = f"{args.year}-{args.month:02d}-{_DIA[args.month]}"

    patrimonio = _publicado(DATASET_BALANCE, "Patrimonio", args.year, args.month)
    utilidad = _publicado(DATASET_INCOME, "Resultado del ejercicio", args.year, args.month)

    print(f"Reconciliación por entidad · período {period_end}")
    print("fuente publicada: SIMBAD (Superset público de la Superintendencia de Bancos)\n")
    print(f"{'entidad':34} {'concepto':12} {'publicado':>18} {'nuestro':>18} {'razón':>7}  ")

    fuera, comparadas = [], 0
    with engine.connect() as conn:
        for simbad, nuestro_nombre in EQUIVALENCIAS.items():
            fila = conn.execute(text(
                "SELECT bd.patrimonio_tecnico, bd.utilidad_neta FROM banks b "
                "JOIN banking_data bd ON bd.bank_id = b.id "
                "WHERE bd.period_end = :pe AND b.name = :n"
            ), {"pe": period_end, "n": nuestro_nombre}).first()
            if fila is None:
                print(f"{nuestro_nombre[:33]:34} {'—':12} {'':>18} {'sin fila':>18}")
                continue
            for concepto, publicado, propio in (
                ("patrimonio", patrimonio.get(simbad), fila[0]),
                ("utilidad", utilidad.get(simbad), fila[1]),
            ):
                if publicado is None or propio is None:
                    print(f"{nuestro_nombre[:33]:34} {concepto:12} "
                          f"{publicado or 0:>18,.0f} {'sin dato':>18}")
                    continue
                propio = float(propio)
                razon = propio / publicado if publicado else 0.0
                ok = abs(razon - 1.0) <= TOLERANCIA
                comparadas += 1
                if not ok:
                    fuera.append(f"{nuestro_nombre}·{concepto}")
                print(f"{nuestro_nombre[:33]:34} {concepto:12} {publicado:>18,.0f} "
                      f"{propio:>18,.0f} {razon:>7.4f}  {'OK' if ok else 'FUERA'}")

    print()
    if comparadas < MINIMO_DE_ENTIDADES * 2:
        # Una aserción de ausencia pasa sola: sin este piso, una consulta que no devuelve
        # nada se leería como «todo reconcilia».
        print(f"✗ solo {comparadas} comparación(es); el sensor exige al menos "
              f"{MINIMO_DE_ENTIDADES} entidades con sus dos cifras")
        return 2
    if fuera:
        print(f"✗ FUERA DE TOLERANCIA (±{TOLERANCIA:.0%}): {', '.join(fuera)}")
        return 1
    print(f"✓ {comparadas} cifras reconciliadas dentro de ±{TOLERANCIA:.0%} "
          "contra el estado publicado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
