# El horizonte que falta en la trayectoria — plan

## Qué se ve hoy en el informe

La sección de trayectoria publica **una** fila. El modelo declara
`bvar.HORIZONTES_CON_TRACK_RECORD = 2` —dos horizontes con track record, y la sección de
escenarios se toma tres párrafos en explicar que del tercero en adelante NO son pronósticos—,
así que el lector cuenta dos y encuentra uno. Nada dice por qué.

La causa está computada y escrita, pero en el lugar equivocado: `emision` la registra en sus
`motivos` —«bvar 2026-Q2: el período ya había cerrado al corte 2026-09-06; el bloque va
atrasado respecto de la fecha de emisión»— y eso vive en el resultado de la operación, que no
llega a ningún informe. Es «servir el dato NO alcanza: hay que pedirlo», y del lado de la
ausencia: el motor sabe por qué falta y la superficie no se entera.

Es la misma forma que el mapa sectorial que desaparecía del Deep Dive: prometer diecisiete
secciones y entregar dieciséis sin decir nada.

## Que no haga falta persistir nada

El informe NO necesita el resultado de la emisión: la causa se reconstruye del propio ledger,
que es lo que ya lee.

* El bloque terminaba en el trimestre que resulta de correr el horizonte presente `h` pasos
  hacia atrás. Si +2T apunta a 2026-Q3, el bloque terminaba en **2026-Q1**.
* El horizonte que falta apunta al trimestre que resulta de correr hacia atrás la diferencia.
  +1T apunta a **2026-Q2**.
* Y estaba vencido si su cierre es anterior o igual al `as_of` de la fila — que es
  exactamente la condición de `emision._es_hacia_adelante`, reproducida y no copiada de un
  texto.

## El arreglo

1. El payload lleva `h` por proyección. Hoy no lo lleva y es lo único que falta para saber
   qué distancia está presente y cuál no.
2. `_horizontes_ausentes(proys)` computa, por modelo, los horizontes relativos de
   `1..HORIZONTES_CON_TRACK_RECORD` que no están, su trimestre objetivo y si ya había cerrado.
3. `_md_trayectoria` lo declara. La prosa en CONSTANTES, y **solo cuando aplica**: una sección
   que siempre avisa es ruido y deja de leerse.

Qué tiene que decir la declaración, y por qué cada pieza:

* **cuántos horizontes se esperan y cuántos hay** — el lector cuenta, y si el informe no
  cuenta primero, la diferencia parece un error de impresión;
* **la causa nombrada**: el bloque terminaba en X, así que +1T apuntaba a Y, cerrado al corte;
* **por qué eso es correcto y no una falla**: un pronóstico de un período ya cerrado se
  evaluaría contra un dato que existía cuando se escribió, y eso infla el track record con
  retrospectiva. No falta un pronóstico: se evitó uno que habría sido mentira;
* **cuándo vuelve**: en cuanto el BCRD publique Y.

## Lo que NO se hace

No se inventa una causa cuando no la hay. Si el horizonte falta y su trimestre **no** estaba
cerrado al corte, se dice que falta y nada más — «no sé por qué» es una respuesta, y
atribuirlo al rezago del bloque sería adivinar. Y si las filas no traen `h`, no se declara
nada: sin la distancia no se puede computar el trimestre objetivo.

## Tests, contra el código viejo primero

- Con solo +2T y el trimestre de +1T cerrado al corte: la sección lo declara, nombra `+1T`,
  el trimestre objetivo, el fin del bloque y la causa. **Falla hoy: no dice nada.**
- **El contraejemplo**: con +1T y +2T presentes NO declara nada. Sin él, un aviso que se
  imprime siempre pasaría el test de arriba.
- Un horizonte ausente cuyo trimestre NO había cerrado: se declara la ausencia sin atribuirle
  el rezago del bloque.
- Filas sin `h`: no se declara nada.
- El payload real lleva `h`.

## Los tres gates

`pytest modules/ shared/ -q` · `ruff check modules/ shared/ app/` ·
`mypy shared/ modules/ app/ --no-incremental | mypy-baseline filter` (exit code del FILTRO).
