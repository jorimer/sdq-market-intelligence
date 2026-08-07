# PROPUESTA — Recalibración de los anclajes absolutos del ISF

> v2 · 2026-08-07 · Estado: **IMPLEMENTADA.** Los anclajes de §3 están en
> `modules/insurance_intel/scoring/isf.py` (`DIMENSIONS`, campo `ref`) junto con la
> winsorización del peer min-max y la corrección del espacio log en `escala`.
> Efecto medido sobre producción: `evidence/ISF-recalibracion-2024.txt`.
> Contexto: `docs/SPEC_PERFIL_SDQ_TAXONOMIA.md` · Plan: `tasks/PLAN_PERFIL_SDQ.md`

---

## 1. Problema

El ISF publicado en producción coloca **21 de 31 aseguradoras** en "En vigilancia" o "Frágil",
con las mayores del mercado (Universal, Sura, Humano, La Colonial) en la mitad inferior y una
compañía pequeña liderando. Para un mercado regulado y solvente, ese retrato no es plausible.

La causa no es el modelo: es que los anclajes absolutos se fijaron contra **rangos teóricamente
posibles**, no contra la distribución observada. Medido contra los datos reales de producción
(35 aseguradoras, cierre 2024):

| Dimensión | Peso | Rango real p10→p90 | Anclaje actual lo→hi | Score mediano |
|---|---|---|---|---|
| Solvencia | 35% | 0.75 → 3.77 | 0.60 → 3.00 | **48** |
| Liquidez | 15% | 1.39 → 4.18 | 0.50 → 5.00 | **28** |
| Escala | 15% | 155M → 18,283M | 500M → 35,000M | **9** |
| Siniestralidad | 20% | 0.05 → 0.79 | 0.85 → 0.25 | 91 |
| Resultado técnico | 15% | −0.06 → 0.23 | −0.05 → 0.20 | 45 |

**Liquidez** es el caso más nítido: el mínimo regulatorio es 1.0 y la aseguradora más ajustada
del mercado está en 1.39 — *ninguna incumple*. Aun así la dimensión entrega una mediana de 28/100.
Seguros Reservas cumple con 72% de colchón y recibe 18.2 puntos. El techo (5.00) casi nadie lo
alcanza, así que todo el panel se aplasta contra el piso.

**Escala**: el techo está en el líder del mercado (35,000M) contra una mediana de 983M → score
mediano 9/100 y el cuartil inferior en ~0.

Solvencia + liquidez + escala pesan **65%** del índice. Con medianas de 48, 28 y 9, es
aritméticamente imposible que el mercado salga bien parado. La distribución observada no es un
juicio sobre el sector: es el artefacto de tres reglas mal puestas.

## 2. Principio propuesto (aplicable a los 4 sectores, no solo al ISF)

> Cada anclaje absoluto tiene un **punto de referencia económico mapeado a 50** — umbral
> regulatorio, breakeven técnico — y sus extremos fijados por **percentiles observados**, no por
> rangos teóricos.

Conserva la virtud del anclaje absoluto (que 60 signifique algo por sí solo, no solo "mejor que el
vecino") sin castigar a un mercado entero por no alcanzar un techo que nadie definió con datos.

Implica cambiar la forma de la función, no solo los números: de **una recta** (`lo→hi` lineal) a
**dos tramos** (`lo→ref` mapea 0→50; `ref→hi` mapea 50→100). Hoy "cumplir el mínimo regulatorio"
cae donde caiga sobre una recta arbitraria; con la curva, cumplir la ley siempre vale 50 — y eso
es defendible ante un cliente o un regulador, que es la prueba que tiene que pasar.

## 3. Anclajes propuestos

| Dimensión | Piso → 0 | **Referencia → 50** | Techo → 100 | Fundamento de la referencia |
|---|---|---|---|---|
| Solvencia | 0.60 | **1.00** | 4.00 | Ley 146-02 Art. 160-161: 1.0 = cumple el margen; techo entre p75 (3.22) y p90 (4.31) |
| Liquidez | 0.60 | **1.00** | 4.00 | Ley 146-02 Art. 162; techo entre p75 (3.43) y p90 (4.31), no 5.0 |
| Siniestralidad | 0.80 | **0.45** | 0.20 | Loss ratio de referencia de la industria |
| Escala | 150M | **1,000M** | 18,000M | p10 / mediana / p90 observados |
| Margen técnico | −0.15 | **0.00** | +0.25 | Breakeven técnico (ancla que ya pedía el spec §5.2) |

Se mantienen sin cambio: los pesos (35/20/15/15/15), los `wabs` del híbrido, y los cortes de banda
(75/60/45).

## 4. Efecto medido (ya no simulado)

Sobre el estado limpio de producción (33 aseguradoras con dato, cierre 2024), la distribución pasa de:

```
ANTES     Sólida 2 · Adecuada 15 · En vigilancia 4 · Frágil 10
DESPUÉS   Sólida 5 · Adecuada 13 · En vigilancia 5 · Frágil  8
```

6 cambios de banda. Detalle completo en `evidence/ISF-recalibracion-2024.txt`.

**La validación cruzada más fuerte:** las **5 aseguradoras que incumplen el margen de solvencia
regulatorio** (índice < 1.0) quedan **todas en el fondo de la tabla** — Creciendo 1.3, Yunén 17.5,
Futuro 33.3, Atlántica 42.1, Multiseguros 44.9 — sin que el índice mire el incumplimiento de forma
explícita. Un índice bien calibrado debería ordenar así por su cuenta; el anterior no lo hacía.

### 4-bis. Dos correcciones que aparecieron al implementar

- **`escala` medía en dos escalas a la vez.** La dimensión se declara logarítmica y la banda
  absoluta lo aplicaba, pero el peer min-max corría en escala **lineal**: contra un techo de
  RD$33.000 millones, una aseguradora en la mediana (RD$983 millones) sacaba ~3 puntos de 100. Es
  buena parte de por qué la dimensión daba mediana 9/100. El min-max ahora respeta el flag.
- **La valla de Tukey no se aplica a paneles chicos** (`_MIN_N = 12`). Medido sobre las 7 AFP del
  ISA, la valla habría acotado los **dos** extremos de `rentabilidad` (5.99-8.78 → 7.21-8.33),
  clampeando a la mejor y la peor en 100 y 0 — exactamente lo contrario de lo que la winsorización
  existe para evitar. Pensiones (7) y fiduciarias (4) quedan por debajo del umbral y **no cambian**.

## 5. Auditoría del dato de solvencia — RESUELTA (2026-08-07)

**La hipótesis del fallback silencioso a `patrimonio/activos` era incorrecta y queda descartada:**
`patrimonio/activos` de La Colonial da 0.2847, no el 0.2962 que muestra el detalle. Tampoco existe
tal fallback en el código — `isf._raw_metric` lee `indice_solvencia` directo, sin ruta alternativa.

**El conector y la fuente están bien.** Verificado contra el archivo oficial
`Indices-de-Solvencia-y-Liquidez-Auditado-2024.xlsx`: el layout de columnas que usa
`sis_solvency_client` (`_COL_SOLV=4`, `_COL_LIQ=8`) es el correcto, y 21 de las 23 aseguradoras
con dato coinciden al cuarto decimal con la fuente.

**La causa real es arquitectónica, y es peor:** hay **dos caminos de cálculo que divergen**.

| Endpoint | Fuente | Estado |
|---|---|---|
| `/rankings` | `compute_isf(db)` — calcula **en vivo** desde `insurance_series` | actual |
| `/{slug}/detail` | lee `InsuranceRating` — **tabla persistida** por el último `score_and_persist` | congelado |

**CAUSA RAÍZ IDENTIFICADA (2026-08-07, corrige el diagnóstico inicial de esta sección):** no es
que "nadie re-sincronice" la tabla — es que **la escritura viene fallando**. El slug oficial de
AGRODOSA (`aseguradora_agropecuaria_dominicana_agrodosa`, 44 caracteres) no entra en el
`VARCHAR(40)` de la columna; en Postgres eso aborta la transacción entera de `score_and_persist`
y hace rollback del sync completo. En SQLite (dev) el límite no se aplica, así que el defecto
solo existía en producción. Verificado: ni AGRODOSA ni Cuna Mutual —la primera del ranking—
existen en `insurance_ratings`. Corregido en PR #644 (migración `c9f2e07b41da`, columnas a
`VARCHAR(80)` + test de regresión sobre el catálogo de nombres).

Consecuencias que se habían medido con la tabla ya congelada:

- **2 aseguradoras con solvencia distinta**: La Colonial (persistida 0.2962 vs. oficial **2.3395**)
  y Seguros Patria (0.4040 vs. **1.4277**). Ambas aparecen incumpliendo el margen regulatorio
  cuando en realidad lo cumplen holgadamente.
- **14 de 35 no tienen las dimensiones regulatorias en la tabla persistida**, aunque el cálculo
  vivo sí las tiene — por eso el detalle de esas entidades no reconstruye su propio score.

**Impacto acotado:** `InsuranceRating` solo la lee `/{slug}/detail` (la ficha de aseguradora en el
frontend). Los informes y la narrativa IA van por `compute_isf`, o sea por el camino vivo.

**Efecto sobre esta propuesta:** los percentiles de la v1 se habían tomado del endpoint de detalle
— es decir, de la tabla congelada, con 23 entidades y 2 valores erróneos. Los del §1 y §3 fueron
**recalculados desde el archivo oficial del SIS** (33 entidades). Los anclajes de solvencia y
liquidez se ajustaron en consecuencia (techo 3.00→4.00 y 3.50→4.00).

## 5-bis. Hallazgo de mercado (no es un defecto: es producto)

Con los valores oficiales, **5 de 33 aseguradoras incumplen el margen de solvencia regulatorio**
(índice < 1.0): Creciendo (0.2493), Futuro (0.7542), Yunén (0.7926), Atlántica (0.9746) y
Multiseguros S.U. (0.9782). Y **2 incumplen liquidez**: Creciendo (0.5930) y Aseguradora
Agropecuaria (0.8889). Es una señal de supervisión que el índice hoy no destaca porque la queda
diluida en el híbrido — vale evaluar exponerla como bandera explícita, al estilo del motor de
Alerta Temprana de banca y pensiones.

## 6. Pendiente separado

**Re-medir la divergencia una vez que la tabla se pueble.** Las diferencias observadas (La Colonial
57.5 en el ranking vs. 54.5 sumando sus dimensiones; Crecer 61.5 vs 62.0) se midieron contra una
tabla que llevaba tiempo sin poder escribirse. Con PR #644 desplegado y el sync corrido hay que
volver a comparar: si siguen divergiendo, entonces sí hay un problema de diseño en tener un camino
vivo y otro persistido, y hay que unificarlos. Si convergen, el defecto era solo la escritura rota.

**Los percentiles de esta propuesta hay que recalcularlos post-sync.** Los del §1 y §3 salieron del
archivo oficial del SIS, así que son correctos para solvencia y liquidez — pero conviene
re-verificarlos contra el estado limpio de producción antes de fijar los anclajes definitivos.

**Orden de implementación acordado con el dueño:** Fix 0 (doble conteo) → auditoría del dato de
solvencia → esta recalibración.

## 6. Evidencia

- Distribuciones y simulación: `evidence/ISF-fix0-delta-2024.txt` y los scripts de recálculo.
- Fuente de los raws: API de producción (`/api/v1/insurance-intel/rankings` y `/{slug}/detail`).
