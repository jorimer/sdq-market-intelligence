# La lectura sectorial publica ocho contracciones que el modelo no proyectó

## Qué se midió (antes de proponer nada)

El informe `SDQ_Proyecciones_Deep-Dive_Sistema_2026-09-05.pdf` publica una tabla sectorial con
**8 de 18 actividades contrayéndose**. Deshaciendo el ajuste declarado de −3,536 pp, el modelo
crudo proyecta **las 18 positivas** (+1,24 % a +7,24 %). Las ocho contracciones son un artefacto
de la reconciliación, no una lectura.

La reconciliación no está mal repartida: está **restando dos cosas que no son la misma medida**.

| | qué mide | dónde |
|---|---|---|
| panel sectorial | `_interanual` → `trimestres[i-4]` → **interanual (YoY)** | `forecasting/sectoral.py:189` |
| BVAR `pib_real` | `DLOG` → `zip(ks, ks[1:])` → **trimestral (QoQ)** | `forecasting/bloque.py:51,127` |

`products_forecast.py:252` pasa `g_pib=float(primera["punto"])` —el punto QoQ del BVAR— a
`reconciliar`, que lo resta de una suma ponderada de crecimientos **interanuales**.

### Medido sobre la serie real de producción (`bcrd.xls.pib_2018.serie_original_indice`, 77 trimestres, 2007-Q1 → 2026-Q1)

```
QoQ (lo que ve el BVAR) : media +1,13 %   mediana +0,94 %
YoY (lo que usa el panel): media +4,54 %   mediana +5,04 %
                           diferencia sistemática: 3,41 pp
```

La brecha publicada es **−3,536 pp**. No es desacuerdo entre modelos: es la diferencia entre
una tasa anual y una trimestral.

### Y hay un segundo defecto, independiente

El BVAR hace el QoQ sobre la serie **ORIGINAL**, que no está desestacionalizada:

```
QoQ medio por trimestre del año, serie ORIGINAL (la que se usa hoy):
  Q1 −0,13 %   Q2 +1,11 %   Q3 −1,13 %   Q4 +4,67 %     amplitud estacional: 5,80 pp
QoQ medio por trimestre, serie DESESTACIONALIZADA (existe en prod, 77 obs):
  Q1 +1,28 %   Q2 +0,61 %   Q3 +1,82 %   Q4 +0,75 %     amplitud estacional: 1,21 pp
```

O sea que el número agregado que el informe titula depende de **en qué trimestre cae el
horizonte**, por calendario. Un pronóstico a Q4 y uno a Q3 no son comparables entre sí.

### La entrada canónica ya declaraba la regla que el bloque rompe

`shared/data/bcrd_excel/canonical.py:352` — `key="pib_real"`:

> `homogenization="…el crecimiento (YoY del volumen) es invariante a la base"`

Y `pib_sectores_origen`: *«el crecimiento se deriva como YoY, que es invariante a la base»*.
El panel sectorial obedece el registro. `bloque.py` no.

### Por qué nadie lo vio: la muestra curada está en la unidad CORRECTA

`_SAMPLE_PAYLOAD` (`products_forecast.py:578`) publica `pib_real` = **3,41 %** y sectoriales de
5,40 / 2,04 / 6,77 / 2,39 / 3,10, con una brecha de solo **−0,42 pp**. La muestra es coherente
**en anual**. Producción emite +0,74 % con −3,54 pp. La muestra escrita a mano enseña cómo
DEBERÍA verse el número; el pipeline produce otro. La vidriera y el producto no coinciden.

---

## Plan

### 1 · `pib_real` del BVAR pasa a interanual  (`forecasting/bloque.py`)

Transformación nueva `DLOG4`: diferencia de logs contra **t−4**. Cura los dos defectos de una:
la vuelve conmensurable con el panel sectorial **y** elimina la estacionalidad, que es
exactamente el motivo por el que la entrada canónica declara el YoY como la medida citable.

*Alternativa considerada y descartada:* mantener QoQ y cambiar a
`serie_desestacionalizada_indice`. Arregla la estacionalidad, **no** la falta de unidad común,
y seguiría titulando una tasa trimestral que todo lector lee como anual.

Costo: la serie pierde 3 observaciones de arranque (4 en vez de 1). Sobre 77 trimestres no
mueve la aguja; hay que **medirlo**, no suponerlo.

### 2 · Un guard: `reconciliar` no puede restar unidades distintas

El defecto sobrevivió porque **nada afirma en ninguna parte** que `g_pib` y
`panel.crecimiento` midan lo mismo. Familia «un guard que falla en silencio».
`reconciliar` recibe la unidad de forma explícita y la contrasta; y un test mide que la
transformación de `bloque` para `pib_real` y `sectoral._interanual` producen la MISMA medida
sobre la misma serie.

### 3 · Publicar `crecimiento_sin_reconciliar`

El campo existe con el comentario *«se publica al lado, para que el ajuste sea visible»* y la
tabla **no lo renderiza**. Con la columna puesta, las ocho contracciones se habrían leído como
lo que eran.

### 4 · La muestra curada se genera, no se escribe a mano

Es la misma lección que ya pagamos en el eje de valuación (`_sample_narrativas_de()`): una
muestra escrita a mano no valida el pipeline, lo tapa.

## Verificación
- [ ] Correr los tests nuevos contra el código VIEJO y ver que FALLAN
- [ ] Medir cuántas observaciones pierde el bloque con DLOG4
- [ ] Re-emitir la proyección y comprobar que la brecha cae al orden de la muestra (~0,4 pp)
- [ ] Comprobar el informe REAL en prod (tiempo de respuesta > 15 s = no es caché)
- [ ] Los tres gates

---

## Dos hallazgos ADYACENTES, de la misma familia (no son la lectura sectorial)

Aparecieron persiguiendo la unidad. Los declaro acá y van por su cuenta, no en este arreglo.

### A · Las proyecciones del BVAR no se pueden puntuar NUNCA

`emision.OBJETIVO = "pib_real"` viaja al ledger como `target_series`. `ledger.puntuar_pendientes`
(`ledger.py:91`) busca `MacroSeries.filter_by(series_code="pib_real")` — y **`pib_real` no es un
código de serie**, es el nombre que el bloque le da a la variable. Verificado en producción:
`GET /api/v1/macro-monitor/series/pib_real` → `observations: []`.

Consecuencia: el informe publica *«Todavía no hay pronósticos puntuados: ninguna de las
proyecciones emitidas alcanzó su período de cierre»*. Se lee como «los trimestres no cerraron
todavía». Lo cierto es que **no pueden cerrar**. Familia «un binding a una serie INEXISTENTE
no falla».

### B · El ledger puntúa una TASA contra un NIVEL

`Nowcast.target_series = PIB_CODE = "bcrd.xls.pib_2018.serie_original_indice"` y su `point` es
un **dlog en %** (~0,4). `puntuar_pendientes` lo compara contra `MacroSeries.value` de ese
código, que es el **índice de volumen** (~133). Un nowcast puntuado daría
`abs_error ≈ |133,13 − 0,38| = 132,75`, y el informe publicaría eso como RMSE.

No explotó todavía **solo porque (A) mantiene la sección vacía**. Arreglar (A) sin (B) hace
que el informe publique un RMSE de ~130 en la primera corrida.

### Y de paso, sobre el titular

`pib_real 2026-Q3 · 0,74 · banda −6,63 … 8,11 · ¿ancla una afirmación? no`

La banda del 80 % mide **14,7 pp** alrededor de un punto de 0,74 — es la varianza estacional
que un VAR sin estacionalidad no puede capturar. Y la proyección **no pasa el gate**: no ancla
ninguna afirmación. Toda la tabla sectorial se reconcilia contra ella igual.
