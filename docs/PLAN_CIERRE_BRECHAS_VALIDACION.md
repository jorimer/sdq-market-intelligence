# Plan de cierre — brechas de validación del catálogo MIP

**Origen:** certificación técnica del 2026-08-16 (`docs/certificacion_validacion_catalogo_mip.md`,
rama `claude/mip-catalog-technical-cert-6093bf`, commit auditado `2721779`).
**Regla del plan:** ninguna fase se cierra con brechas abiertas. Cada fase termina en un **Status de
avance** con criterios de aceptación verificables por comando, no por opinión.

---

## 0. Diagnóstico: las 21 brechas y su causa raíz

Las brechas no son 21 problemas independientes. **Trece de ellas comparten una sola causa raíz.**

### La causa raíz: los reportes de validación se invalidan por RELOJ, no por su INSUMO

Todo reporte de validación es un artefacto persistido (`AppSetting`) que se recalcula por cadencia
fija. Ninguno se recalcula cuando cambia el dato o el score que lo produjo. Estado en producción al
abrir el plan:

| Operación | ¿Habilitada? | Cadencia | Última corrida | Próxima |
|---|---|---|---|---|
| `backtest` (banca) | sí | 720 h (30 d) | 2026-07-27 | 2026-08-26 |
| `irmp-backtest` | sí | 720 h | 2026-07-27 | — |
| `trade-backtest` | sí | 720 h | 2026-07-27 | — |
| `idm-convergent-validity` | sí | 2.160 h (90 d) | 2026-08-10 | — |
| `esg-backtest` | sí | **8.760 h (1 año)** | 2026-06-27 | **2027-06-27** |
| `insurance-backtest` | **NO** | 24 h | nunca corrió | — |
| `pension-backtest` | **NO** | on-demand | 2026-07-03 | — |

**Así se produjo el defecto principal.** La recalibración `02fcdd2` (2026-08-07) cambió el
`overall_score`. El backtest de banca tenía `next_run_at = 2026-08-26`. Entre el 7 y el 26 de agosto
—19 días— producción publicó un Gini de 0.4436 calculado con el score anterior. Nadie lo vio porque
**el sistema no sabe que el reporte quedó huérfano de su insumo.**

Es la misma clase de defecto que la doctrina ya describe para la caché de narrativas (`CLAUDE.md`):
un artefacto persistido cuya invalidación no está cableada a sus entradas. Y ya reincidió entre
motores, que es exactamente la condición que la doctrina marca para exigir **test estructural**, no
lección escrita.

### Inventario completo

| # | Brecha | Clase | Fase |
|---|---|---|---|
| A1 | Banca: prod sirvió Gini 0.44 vs 0.16 real durante 19 d | raíz | 1 |
| A2 | `insurance-backtest` deshabilitada | raíz | 1 |
| A3 | `pension-backtest` deshabilitada, corrió 1 vez (3-jul) | raíz | 1 |
| A4 | `esg-backtest` con cadencia anual (próxima: jun-2027) | raíz | 1 |
| A5 | `idm-convergent-validity` a 90 d | raíz | 1 |
| A6 | `irmp`/`trade` a 30 d, mismo desacople | raíz | 1 |
| A7 | No existe señal de "reporte obsoleto respecto de su insumo" | raíz | 1 |
| A8 | Cifras de irmp/trade/esg/sector sin recalcular desde jun/jul | raíz | 0 |
| B1 | Curva por banda de banca no ordena riesgo; anomalía en banda **superior** (Sólida 23,1 %, n=516) | método | 2 |
| B2 | El caveat lo llama "ruido en tiers intermedios" — describe mal el defecto | método | 2 |
| B3 | Discriminación cayó 0.44 → 0.16 tras `02fcdd2`, mismo panel | método | 2 |
| C1 | Pensiones: resultado **concluyente** (Gini 0.1594) sin endpoint de lectura | cobertura | 3 |
| C2 | Seguros: ninguna señal concluyente al recalcular | cobertura | 3 |
| C3 | IAI sectorial: resultado nulo/negativo (IC −0.03, spread −1,13) | cobertura | 3 |
| C4 | Siete ejes sin validación alguna | cobertura | 4 |
| C5 | Disclaimer del IRMP dice "5 países"; el panel es 24 / 260 obs | texto | 3 |
| D1 | `energy`: `en_scores` vacía en prod (sync SIE) | dato | 5 |
| D2 | `telecom`: dato congelado en 2022-Q1 | dato | 5 |
| D3 | Readiness auditado hace ~240 commits (24-jun) | dato | 5 |
| E1 | Catálogo comercial dice 14 ejes; son 16 | comercial | 6 |
| E2 | Material comercial asume "1 validado / 13 roadmap" | comercial | 6 |

---

## Fase 0 — Línea base certificada

**Objetivo:** que exista un número vigente y trazable para **cada** eje con motor de validación, antes
de tocar código. Sin esto, cualquier arreglo posterior se mide contra una referencia falsa.

### Acciones
1. Recalcular por consola las operaciones de validación:
   `backtest`, `irmp-backtest`, `trade-backtest`, `esg-backtest`, `idm-convergent-validity`,
   `sector-gate-e`, `insurance-backtest`, `pension-backtest` (vía `POST /api/v1/operations/{name}/run`).
2. Capturar cada reporte con su `generated_at` y volcarlo a `evidence/validacion_baseline_YYYY-MM-DD.json`,
   **comiteado**. Es la foto contra la que se comparan las fases siguientes.
3. Registrar por eje: métrica, valor, IC, N, eventos, `conclusive`, `monotonic`.
4. Anotar los deltas contra la certificación del 16-ago.

### Status de avance — **CERRADA** (2026-08-19)
- [x] Los 8 reportes tienen `generated_at` del día de la corrida.
- [x] `evidence/validacion_baseline_2026-08-19.json` comiteado, con las 9 superficies y sus deltas.
- [x] Cada eje tiene veredicto explícito → [`docs/LINEA_BASE_VALIDACION.md`](LINEA_BASE_VALIDACION.md).
- [x] **Cero** ejes con motor y sin cifra vigente.

---

## Fase 1 — Que el número no pueda volver a mentir

**Objetivo:** eliminar la causa raíz. Un reporte de validación no puede sobrevivir al cambio del dato
o del score que lo produjo. Cierra A1–A8.

### Acciones
1. **Invalidación por evento, no por reloj.** Cablear cada recálculo de validación al evento que lo
   invalida, con la cascada `triggers=[...]` que la consola ya soporta (el mismo patrón con que
   `sector-snapshot` dispara `sector-gate-e` y `bcrd-comunicados-sync` dispara `tpm-model-train`):
   - `rescore` / recalibración de banca → `backtest`
   - sync de estados financieros de seguros → `insurance-backtest`
   - sync SIPEN → `pension-backtest`
   - sync IRMP/trade/ESG/social → su backtest respectivo
2. **Huella de insumo en el reporte.** Cada reporte persiste el *fingerprint* de lo que lo produjo
   (versión del scoring + período máximo del panel + N). Si el fingerprint vigente ≠ el del reporte,
   el reporte se sirve **marcado como obsoleto**, no como verdad.
3. **Corregir las cadencias absurdas**: ESG pasa de anual a la cadencia de su fuente; el reloj queda
   como red de seguridad, no como mecanismo primario. Los dos motores `on_demand`
   (`insurance-backtest`, `pension-backtest`) no se agendan: se cuelgan de su sync.
4. **Test estructural** (`ast`) que recorre `modules/*/validation/` y exige, para cada motor: (a) un
   recálculo suscrito a un evento, y (b) fingerprint de insumo — o una excepción declarada con motivo.
   Al escribir el glob, declarar explícitamente qué queda afuera (`tpm_modeling` y
   `sib_historical_backtest` no viven bajo `validation/`).
5. **Superficie de obsolescencia**: la consola de operaciones muestra, por eje, si su validación está
   al día respecto de su insumo.

### Status de avance — **CERRADA** (2026-08-19, verificada en producción)
- [x] Re-puntuar dispara la validación **sin intervención**. Verificado en PRODUCCIÓN, no en dev:
      `perfil-sdq-backfill` terminó 15:07:38 y el backtest corrió solo a las 15:07:39 con
      `origin: cascade` en el historial de operaciones.
- [x] Los 8 reportes exponen `input_fingerprint`. Antes de resellarlos, los 8 respondían
      `stale: null` («reporte sin huella») — el estado indeterminado se comportó como se
      diseñó; tras recalcularlos, los 8 responden `stale: false`.
- [x] `insurance-backtest` y `pension-backtest` colgadas de sus syncs (son `on_demand`: no se
      agendan, se disparan). `esg-backtest` pasó de 8.760 h a 2.160 h **en producción**
      (próxima corrida: 2026-11-17, antes 2027-06-27).
- [x] El test estructural tiene dientes, verificado revirtiendo un motor a propósito. Su primera
      versión NO los tenía —comparaba la clave por substring y `backtest_report` está contenido
      en `insurance_backtest_report`—; ahora resuelve el archivo escritor por AST.
- [x] Los tres gates en verde (4.411 tests · ruff · mypy con el baseline sincronizado).
- [x] **Cero** reportes de validación cuya invalidación dependa solo del reloj.

> Hallazgo lateral: el reporte de seguros se escribía desde DOS puertas (la operación y el POST
> de la API) y ninguna estampaba fecha. Hay una sola puerta y un test que la exige.

---

## Fase 2 — Los defectos de banca

**Objetivo:** que la credencial principal sea defendible línea por línea. Cierra B1–B3.

### Acciones
1. **Investigar la caída 0.44 → 0.16** (`02fcdd2`, 2026-08-07). Panel idéntico (1.693/301), así que
   el cambio está en `overall_score`. Reconstruir el backtest con el score anterior y con el nuevo
   sobre el mismo panel y responder, con evidencia: ¿la recalibración corrigió una saturación y
   **degradó** la discriminación, o el 0.44 medía otra cosa? El resultado manda sobre el resto de la
   fase — si la recalibración degradó el score, el arreglo es del score, no del reporte.
2. **La curva por banda.** Hoy: Sólida 23,1 % (n=516) · Adecuada 13,7 % · En vigilancia 9,9 % ·
   Frágil 27,6 %. La anomalía está en la banda **superior**, con N grande: no es ruido muestral.
   Diagnosticar si el corte de `BANDAS_RESILIENCIA` (75/60/45) está mal ubicado respecto de la
   distribución real del score recalibrado. Resolver, o **retirar la tabla por banda** de toda
   superficie publicada mientras no ordene riesgo.
3. **Corregir el texto del caveat** (`modules/banking_score/validation/report.py`): debe nombrar
   *cuál* banda viola la monotonía y con qué N, computado del propio resultado — no una frase fija que
   afirma "tiers intermedios". Es la doctrina de que las relaciones se **computan**, no se narran.
4. **Test de regresión**: si la curva no es monótona, la superficie publicada no puede presentarla
   como ordenamiento de riesgo.

### Status de avance — **CERRADA** en lo verificable; una decisión de scoring queda abierta
- [x] Informe escrito con evidencia reproducible → [`docs/DIAGNOSTICO_DISCRIMINACION_BANCA.md`](DIAGNOSTICO_DISCRIMINACION_BANCA.md).
      **La recalibración degradó la discriminación**: mismo panel, 0,3444 [0,275 · 0,409] con las
      curvas previas contra 0,1615 [0,092 · 0,233] con las vigentes — los IC no se solapan. La
      causa: `solidez` (40 % del peso) tiene Gini **−0,1944** con el IC entero bajo cero.
- [x] La curva por banda NO ordena el riesgo y ninguna superficie la presenta como si lo
      hiciera: API (`by_tier_ordena_riesgo` + `monotonic_violations`), frontend (título, aviso
      con la inversión nombrada y barras en tono de advertencia) y PDF de criterios (hereda el
      caveat computado). La cuarta superficie que el plan pedía revisar —el contexto de IA— no
      consume el backtest: los `AI_CONTEXT_FILES` de banca no leen `by_tier`. Declarado.
- [x] El caveat nombra la banda real y su N, computados del resultado.
- [x] Test de regresión sobre la curva REAL de producción (Sólida → Adecuada, n=516).
- [x] **Cero** superficies mostrando una tabla que se contradice con su propio caveat.
- [ ] **DECISIÓN DEL DUEÑO** (§4 del informe): qué hacer con `solidez` invertida y con un
      desenlace que es 83 % pérdidas sostenidas, 22 % crédito y 0 % solvencia. La recomendación
      es re-especificar el desenlace primero y decidir sobre el score con ese resultado.

> Hallazgo que la pregunta original no anticipaba: de los 301 eventos del desenlace, **250**
> los aporta la regla de ROA<0 sostenido y **cero** la de solvencia, que nunca disparó. Contra
> la regla de CRÉDITO el score discrimina **invertido** (−0,1437 [−0,235 · −0,050]). El
> reporte ahora publica esa composición y la declara en sus caveats.

---

## Fase 3 — Cobertura de los ejes que YA tienen motor

**Objetivo:** que todo motor existente tenga su resultado legible y su veredicto declarado. Cierra
C1–C3 y C5.

### Acciones
1. **Pensiones (C1).** Tiene resultado **concluyente** —señal `return`: Gini 0.1594, IC [0.099, 0.217],
   n=1.590, 665 eventos— **invisible**: no hay ruta de validación en el `openapi.json` de producción.
   Exponer `GET /api/v1/pension-intel/validation` con el mismo contrato que seguros. Es la brecha más
   barata del catálogo: el motor ya está escrito y testeado.
2. **Seguros (C2).** Ninguna señal es concluyente con el panel actual (solvencia 0.093, underwriting
   0.156; ambos IC cruzan cero). Decisión explícita entre: (a) ampliar el panel con más años de
   estados auditados; (b) probar una señal con más poder; (c) **declarar** que el ISF no tiene
   validación concluyente y bloquear su uso como credencial. Cualquiera de las tres cierra la brecha;
   dejarlo sin decidir, no.
3. **IAI sectorial (C3).** Resultado nulo/negativo (IC medio anual −0.03; spread de quintiles −1,13).
   Afecta a `economic_structure` **y** a `agribusiness`, que se sirve del mismo motor. Decidir entre:
   (a) el IAI no pretende predecir empleo y hay que validarlo contra el desenlace que sí targetea;
   (b) el índice necesita rediseño; (c) se declara descriptivo, no predictivo. Y propagar la decisión
   a las dos superficies.
4. **Disclaimer del IRMP (C5).** Dice "5 países (N pequeño)" cuando el panel es de 24 países y 260
   observaciones; el 5 son los pares de validez convergente contra S&P. Corregir para que el número
   se compute del reporte, no esté escrito a mano.

### Status de avance — criterios de cierre
- [ ] `GET /api/v1/pension-intel/validation` en producción, con cifra recalculada.
- [ ] Seguros: decisión tomada, implementada y reflejada en el producto (readiness G5 incluido).
- [ ] IAI: decisión tomada y propagada a `economic_structure` **y** `agribusiness`.
- [ ] Ningún disclaimer con cifras escritas a mano: todas computadas del reporte.
- [ ] **Cero** motores de validación cuyo resultado no sea legible por API.

---

## Fase 4 — Los siete ejes sin validación

**Objetivo:** que ningún eje del catálogo quede sin estado declarado. Cierra C4.

Ejes: `tourism`, `free_zones`, `construction`, `energy`, `telecom`, `agribusiness`, `law`.

### Acciones
1. **Triaje por viabilidad**, con un criterio único: ¿existe un desenlace realizado, observable e
   independiente del índice? Para cada eje, resolver a uno de tres destinos:
   - **Validable ahora** → construir su Gate E con la maquinaria compartida.
   - **Validable cuando llegue el dato** → declarar qué dato falta y de qué fuente.
   - **No validable por naturaleza** → declararlo en el producto, como ya hace `construction`
     ("índice preliminar, aún sin validación retrospectiva").
2. **Candidatos con desenlace plausible** (a confirmar en el triaje): turismo → llegadas/ocupación
   realizadas; zonas francas → exportaciones y empleo de CNZFE; construcción → permisos ejecutados
   vs. iniciados; telecom → penetración realizada.
3. **`law` es un caso aparte**: su "desenlace" es el cumplimiento de la meta legal, que el propio eje
   mide. Es autoreferencial y probablemente corresponda declararlo no-backtesteable, no forzarle un
   Gate E artificial.
4. **Regla anti-hueco**: cada eje sin validación debe declararlo en su propio producto, con el mismo
   estándar que `construction` ya cumple. Un eje que calla su falta de validación es peor que uno que
   la declara.

### Status de avance — criterios de cierre
- [ ] Los 7 ejes con destino asignado y escrito.
- [ ] Los validables ahora, con su Gate E corriendo y su cifra publicada.
- [ ] Los demás, declarando su estado **en el producto**, no solo en un documento interno.
- [ ] Test estructural que exige, para cada eje del catálogo, o un motor de validación o una
      declaración explícita de por qué no lo tiene.
- [ ] **Cero** ejes del catálogo sin estado de validación declarado.

---

## Fase 5 — Dato y madurez

**Objetivo:** que la madurez publicada sea la real. Cierra D1–D3.

### Acciones
1. **`energy` (D1):** correr el sync SIE en producción; `en_scores` estaba vacía. Según la auditoría
   de junio, eso lo lleva de 0.37 a ~0.81 → Pulse publicable.
2. **`telecom` (D2):** el boletín INDOTEL está congelado en 2022-Q1. Decidir: buscar fuente alterna,
   o mantener el eje declarado como congelado —lo que la auditoría llamó "honesto por diseño"— pero
   **decidido**, no heredado.
3. **Re-auditar readiness (D3)** de los **16** ejes: el único dato trazable es del 2026-06-24, unos
   240 commits atrás, y cubría 10. Correr `scripts/audit_p4_products.py` contra prod y comitear la
   evidencia nueva.
4. Verificar que ningún eje publique un nivel de producto por encima de su readiness real.

### Status de avance — criterios de cierre
- [ ] Auditoría de readiness fresca para los 16 ejes, comiteada en `evidence/`.
- [ ] `energy` con datos en prod y su readiness recomputado.
- [ ] `telecom` con decisión escrita.
- [ ] Ningún eje publicando por encima de su readiness.
- [ ] **Cero** cifras de madurez en circulación con más de una semana.

---

## Fase 6 — Coherencia comercial

**Objetivo:** que ninguna afirmación comercial carezca de cifra certificada detrás. Cierra E1–E2.

### Acciones
1. **Catálogo v4 sobre 16 ejes**, generado del registro (`scripts/build_catalogo_v3.py` lee
   `PRODUCT_CATALOG`, así que la lista sale sola; hay que actualizar el texto que dice "14").
2. **Tiering real** en el material comercial, con los seis grupos de la certificación (validado contra
   evento real / concluyente / convergente / parcial / corrido y no concluyente / sin validar).
3. **Corregir el deck**: sus cuatro cifras de banca son correctas, pero debe decir **tres cohortes
   evaluables**, no seis, y no presentar el Gini 0.16 como validación contra quiebras.
4. **Gate de publicación**: ninguna cifra de validación entra a material comercial si su reporte está
   marcado `stale` (la marca que crea la Fase 1). Esto conecta el arreglo técnico con el riesgo
   comercial — es lo que evita que el episodio del 0.44 se repita en un PDF entregado a un cliente.
5. Registrar el cambio de metodología en `shared/doctrine/changelog.yaml`, que es lo que responde por
   qué la cifra de un informe viejo ya no coincide.

### Status de avance — criterios de cierre
- [ ] Catálogo v4 publicado sobre 16 ejes.
- [ ] Deck corregido en cohorte (3, no 6) y en la naturaleza del desenlace.
- [ ] Todo material comercial vigente trazable a una cifra certificada y no obsoleta.
- [ ] Changelog de metodología actualizado.
- [ ] **Cero** afirmaciones comerciales sin cifra certificada detrás.

---

## Orden y dependencias

```
Fase 0 (línea base) ─┬─> Fase 1 (causa raíz) ─┬─> Fase 2 (defectos de banca) ─┐
                     │                        └─> Fase 3 (motores existentes) ─┤
                     └─> Fase 5 (dato/madurez) ──────────────────────────────┐ │
                                              Fase 4 (los siete) ────────────┤ │
                                                                             └─┴─> Fase 6 (comercial)
```

- **La Fase 0 va primero, sin excepción**: sin línea base, las demás se miden contra una referencia falsa.
- **La Fase 1 antes que 2/3/4**: arreglar cifras sin arreglar la invalidación las deja envejecer igual.
- **La Fase 6 va última**: es la única que produce material externo, y depende de que todo lo demás
  esté certificado.
- **La Fase 5 es independiente** de 1–4 y puede ir en paralelo.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Recalcular tumba más veredictos (ya pasó con seguros) | Es el objetivo, no un efecto adverso. Mejor descubrirlo acá que en la reunión |
| La Fase 2 concluye que la recalibración degradó el score | Se vuelve trabajo de scoring, no de reporte. Puede alargar la Fase 2; no bloquea 3-5 |
| El triaje de la Fase 4 concluye que varios ejes no son validables | Resultado válido: el objetivo es estado **declarado**, no validación forzada |
| Aparecen ejes nuevos durante el plan (pasó dos veces desde julio) | El test estructural de la Fase 4 los obliga a declarar estado al entrar al catálogo |
