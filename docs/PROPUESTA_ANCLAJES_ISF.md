# PROPUESTA — Recalibración de los anclajes absolutos del ISF

> v1 · 2026-08-07 · Estado: **aprobada en principio por el dueño, GUARDADA para implementar
> más adelante.** No implementar todavía: depende de la auditoría del dato de solvencia
> (ver §5) y del Fix 0 del doble conteo.
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

## 4. Efecto simulado

Sobre los raws reales de producción, la distribución de bandas pasa de:

```
ACTUAL      Sólida  0 · Adecuada 10 · En vigilancia  4 · Frágil 9
PROPUESTA   Sólida  4 · Adecuada  9 · En vigilancia  3 · Frágil 7
```

No es un ablande general: Yunén, Patria y Futuro siguen en Frágil. Corrige el sesgo y deja que la
dimensión discrimine.

⚠️ **La simulación es DIRECCIONAL, no definitiva** — ver §5.

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

Nada re-sincroniza la tabla persistida cuando cambian los datos vivos, así que el detalle sirve el
ISF de la última corrida de sync mientras el ranking sirve el de hoy. Consecuencias medidas:

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

**El detalle no reconstruye el ranking.** Aun con los datos sincronizados, La Colonial da 57.5 en el
ranking y 54.5 sumando sus propias dimensiones ponderadas (Crecer: 61.5 vs 62.0). Hay que unificar
los dos caminos de cálculo — o el detalle recalcula en vivo, o el ranking lee lo persistido, pero no
uno de cada uno.

**Orden de implementación acordado con el dueño:** Fix 0 (doble conteo) → auditoría del dato de
solvencia → esta recalibración.

## 6. Evidencia

- Distribuciones y simulación: `evidence/ISF-fix0-delta-2024.txt` y los scripts de recálculo.
- Fuente de los raws: API de producción (`/api/v1/insurance-intel/rankings` y `/{slug}/detail`).
