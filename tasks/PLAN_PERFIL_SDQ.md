# PLAN FINO — Perfil SDQ (2 ejes) + Fix 0 del ISF

> v1 · 2026-08-07 · Spec rector: `docs/SPEC_PERFIL_SDQ_TAXONOMIA.md` (v1.3).
> Estado: **desglose propuesto, pendiente aprobación del dueño antes de tocar código**
> (regla Plan First). Nada de esto se implementó todavía.

---

## 0. Verificación previa — HECHA (2026-08-07)

Ejecutada antes de proponer, según §12 del spec. Resultados:

### 0.1 Greps de alcance (§1) — el alcance CRECIÓ desde el corte del spec (2026-08-06)

| Patrón | Spec v1.3 | Real hoy | Δ |
|---|---|---|---|
| `rating_tier` | 53 arch · 132 occ | **60 arch · 165 occ** | +7 / +33 |
| `RATING_SCALE` | 6 arch · 18 occ | **7 arch · 20 occ** | +1 / +2 |
| `SDQ-<letras>` | 44 arch · 186 occ | **47 arch · 252 occ** | +3 / +66 |

La migración de superficie (Fase 4) es ~35% más grande de lo estimado en el spec.

### 0.2 Bug §5.1 — CONFIRMADO contra el Excel crudo del SIS 2024, no inferido

Descargado `Estados-Financieros-Auditados-por-cia-2024.xlsx` (35 hojas). El catálogo real:

- `5101 RECLAMACIONES PAGADAS POR SINIESTRO` (personas) y `5301 RECLAMACIONES PAGADAS POR
  SINIESTROS` (generales) **viven dentro de la sección 5** → `gastos_totales =
  leaves_sum("5", ndig=6)` los incluye.
- `siniestros_pagados` se extrae de esos MISMOS dos headers.
- **Doble conteo real y material.** Mediana de siniestros dentro de `gastos_totales` = **19.0%**;
  máximo observado **46.9%** (Humano Seguros).

### 0.3 CORRECCIÓN AL SPEC §5.2 — el expense ratio propuesto NO es correcto

El spec propone `expense ratio = gastos_totales − siniestros`. **Eso no funciona.** La sección 5
del catálogo dominicano no es "gastos" en sentido económico: es el lado deudor del estado técnico
bruto. Contiene además de siniestros y gastos operativos:

- **Primas de reaseguro cedidas** (`5106-5111`, `5305-5310`) — mediana **8.3%** de `gastos_totales`,
  hasta **30.3%** (Worldwide).
- **Movimientos de reservas del presente ejercicio** (`5112-5115`, `5311-5314`, `5317`, `5414-5417`).
- Retrocesiones del reaseguro aceptado (`5208-5213`, `5408-5413`).

Sacar solo los siniestros dejaría un "expense ratio" inflado por cesión y reservas — un número sin
significado actuarial. **El expense ratio debe construirse por selección explícita de cuentas:**
comisiones a intermediarios (`5103`, `5104`, `5302`, `5303`) + gastos generales y administrativos
(`5116`, `5218`, `5316`, `5419`) + otros gastos de operación (`5501`, `5502`). Mediana observada de
ese bloque: **27.1%** de `gastos_totales`.

### 0.4 §5.5 Reaseguro — DISPONIBLE en la fuente. Era brecha de ingeniería, la v1.3 acertó

Existen en el catálogo, hoy no extraídas:
- **Cesión:** `5106-5111` (personas) + `5305-5310` (generales), por tipo (contractual / facultativo /
  no proporcional, local / exterior).
- **Recuperables:** `4107-4108`, `4307-4308` (siniestros a cargo de reaseguradores), `4110`, `4311`,
  `4313` (reservas a cargo de reaseguradores).

### 0.5 §5.6 Desglose por ramo — DISPONIBLE. Confirmado, no supuesto

Los leaves de 6 dígitos SON ramos. `4301`→15 ramos generales (`430101 INCENDIO…` … `430115 OTRAS
FIANZAS`); `5301`→los mismos 15; `4101`→8 ramos de personas; `5101`→5. **El desglose por ramo está
en lo que ya se lee y se pierde en la agregación.** Loss ratio por ramo es computable hoy.

### 0.6 §5.3/§5.4 Ingesta multi-año — YA EXISTE, no hay que construirla

`financials_sync.sis_financials_history_sync(since_year=2018)` ya ingiere la historia completa.
El portal SIS ofrece **18 años (2007-2024)**, `.xlsx` desde 2018. El docstring del módulo dice
"latest" pero la función de historia existe y persiste por período. Falta confirmar qué años están
efectivamente cargados **en prod**.
⚠️ Nota aparte: `isf._load_financials` toma el valor **más reciente por series_code**, mezclando
períodos si una compañía deja de reportar una serie. Revisar al tocar multi-año.

### 0.7 Acceso a datos — parcial

- **Prod DB: NO hay acceso desde este entorno.** `.env` apunta a SQLite dev y la dev DB **no tiene
  ninguna tabla `insurance_*`** (confirmado). Consistente con [[dev-env-key-and-db-gaps]].
- **Pero seguros no necesita prod para casi nada:** el ISF se puede recomputar entero desde el Excel
  público del SIS (2018-2024) en local. Eso desbloquea sin prod: distribución real, cortes por
  percentil, gate de peso×dispersión (§5.8), correlación entre ejes (§8) y el test de estabilidad de
  ranking (§5.9).
- **Sí requieren prod:** solvencia/liquidez regulatorias (vienen de Power BI vía `sis_solvency_client`,
  no del Excel), cobertura de `patrimonio`/`activos_totales` por AFP (§6.2), y distribuciones de
  banca/fiduciarias.

### 0.8 Blast radius del Fix 0

`scoring/isf.py` · `products.py:218,418,425` · `ai_context.py:115` · `validation/backtest.py:148-149`
· `tests/test_insurance_intel.py:117-138`. Acotado.

---

## FASE 0 — Fix del doble conteo en el ISF de producción (§5.1) · CÓDIGO COMPLETO

- [x] **0a.** Extractor: series nuevas `gastos_operativos` (comisiones + G&A + otros gastos de
      operación del seguro DIRECTO, por selección explícita), `primas_cedidas`,
      `recuperables_reaseguro`. Helper `heads_sum(prefijos, *kws)` selecciona por sección
      (51xx/53xx = directo) para que numerador y denominador queden en el mismo libro.
      `gastos_totales` se mantiene (lo usa el backtest) con una advertencia de qué es realmente.
      Códigos verificados estables en 2018/2020/2022/2024.
- [x] **0b.** `isf.py`: `resultado_tecnico` = margen técnico = `1 − (siniestros + gastos_operativos)
      / primas`. Mutuamente excluyente con `siniestralidad` por construcción. Peso 0.15 y anclajes
      SIN cambio a propósito, para que el delta sea atribuible solo al cambio de definición.
- [x] **0c.** Ancla verificada contra el Excel real (Humano, el caso extremo): `gastos_operativos`
      = 6,673M vs. `gastos_totales` = 24,937M; el expense ratio ya no contiene siniestros (11,700M)
      ni cesión. Combined ratio 88.5%.
- [x] **0d.** Trazabilidad: `MODEL_VERSION` 0.1 → **0.2**. Todo score recalculado queda marcado, así
      un cambio de banda entre versiones se lee como metodológico y no como deterioro de la entidad.
      (Seguros no tiene tabla de `rating_actions` — el registro es la versión de modelo + la
      evidencia del delta versionada en el repo.)
- [x] **0e.** Delta reportado y aprobado por el dueño. Validación final con el motor real sobre
      datos oficiales completos: **10 cambios de banda**, 9 hacia arriba y 1 hacia abajo
      (Creciendo Seguros, que la definición vieja premiaba con el score MÁXIMO del panel teniendo
      un combined ratio de 831%). Evidencia: `evidence/ISF-fix0-delta-2024.txt`.
- [x] **0f.** Tres gates verdes: pytest **3017 passed**, ruff limpio, mypy-baseline sin errores
      nuevos. Tests nuevos: doble conteo, brecha declarada sin `gastos_operativos`, y separación
      de siniestros/cesión en el extractor.
- [x] **0g.** `validation/backtest.py` replicaba la misma fórmula defectuosa → corregido a la misma
      definición. Un período sin `gastos_operativos` queda FUERA del backtest en vez de
      reconstruirse con la fórmula vieja.

### ✅ DESPLEGADO Y VERIFICADO EN PRODUCCIÓN (2026-08-07)

- [x] **0h.** PR #643 mergeado y desplegado + re-ingesta corrida. El histórico 2018→2024 quedó
      cargado: **2.784 filas de series**, las tres nuevas en los siete años.
      ⚠️ Aprendizaje operativo: el primer `history/sync` devolvió 500 por una **carrera con la
      migración**, que aún corría. Reintentado después, pasó en 23 s. No había nada roto en el sync.
- [x] **0i.** Verificado en prod: **31 con banda, 31 con cobertura completa** y los **10 cambios de
      banda coinciden exactamente** con `evidence/ISF-fix0-delta-2024.txt` (Reservas 75.4 Sólida,
      La Colonial 65.6, HYLSEG 66.6, Angloamericana 63.3, Agropecuaria 63.3, APS 63.3, Sura 61.0,
      Universal 60.1, Humano 46.8, Cía. Dominicana 45.2).
      Distribución: de `1 Sólida / 9 Adecuada / 9 En vigilancia / 12 Frágil` a **`2 / 15 / 4 / 10`**.

## FASE 0-bis — Defectos encontrados durante la auditoría (nuevos, no estaban en el spec)

- [x] **La "tabla congelada" tenía causa raíz, no era falta de sync (PR #644).** El slug oficial de
      AGRODOSA (`aseguradora_agropecuaria_dominicana_agrodosa`, 44 car.) no entra en el `VARCHAR(40)`
      de `entity_slug`. En Postgres eso aborta la transacción de `score_and_persist` y hace rollback
      del sync completo; en SQLite el ancho no se aplica, así que el defecto solo existía en prod
      ([[dev-prod-sqlite-postgres-parity]] otra vez). Verificado: ni AGRODOSA ni Cuna Mutual —la
      primera del ranking— existían en `insurance_ratings`. Migración `c9f2e07b41da` a `VARCHAR(80)`
      + test de regresión que corre contra el catálogo de nombres, no contra la base.
      **Lección de método:** un síntoma bien medido no es una causa diagnosticada. Documenté
      "dos caminos que nadie sincroniza" cuando en realidad uno no podía escribir.
- [x] **La divergencia ranking/detalle tenía DOS causas, y las dos están cerradas.** Además del
      `VARCHAR(40)`, `/{slug}/detail` hacía `.first()` sin `order_by`: con una fila por aseguradora
      daba igual, pero al poblar el histórico pasaron a ser siete por entidad y devolvía una
      arbitraria (La Colonial: ranking 65.6, ficha 54.5). Corregido en **PR #645**
      (`order_by(period.desc())` + `period` en la respuesta, para que la ficha sea auditable).
      **Verificado en prod: las 35 coinciden ranking↔detalle, y la suma ponderada de dimensiones
      reconstruye el score publicado en todas.**
      **Lección:** poblar datos correctos destapa bugs que la escasez de datos escondía. El
      `.first()` era latente desde siempre; solo se volvió visible al haber más de un período.
- [x] **Winsorizar el pool de peer min-max + recalibrar anclajes (PR #647).** Implementados juntos
      a propósito: por separado, Seguros Universal bajaba de banda con la winsorización y volvía a
      subir con los anclajes — un vaivén visible en producción sin ningún significado.
      `shared.indices.normalization.robust_bounds` (valla de Tukey) es único para los tres motores,
      respetando la doctrina de `shared/indices` de no reimplementar normalización.
      **Umbral `_MIN_N = 12`:** con paneles chicos la valla recorta dispersión legítima — medido
      sobre las 7 AFP, habría acotado los dos extremos de `rentabilidad`. Pensiones y fiduciarias
      quedan debajo del umbral y no cambian.
      De regalo: `escala` medía en **dos escalas a la vez** (banda absoluta en log, min-max en
      lineal), que es buena parte de por qué daba mediana 9/100.
      Efecto: 6 cambios de banda; `evidence/ISF-recalibracion-2024.txt`.
- [x] **Bandera de incumplimiento regulatorio (PR #648).** `incumple_solvencia` /
      `incumple_liquidez` en cada fila del ranking. Incumplir la Ley 146-02 es un hecho binario,
      no un matiz de score, y diluido en el híbrido ponderado no se distinguía de "flojo en otra
      dimensión". Sin dato ingerido la bandera es `None`, no `False`: no se puede afirmar que
      cumple.
- [x] **FiduAPAP — es brecha de FUENTE, no de ingeniería (PR #648).** Verificado contra el portal
      de la SB: su ficha responde 200 con contenido pero **cero PDFs**, mientras las otras cuatro
      publican seis cada una; y el slug es el correcto, sale del índice oficial. No se fuerza: se
      declara. `SCORABLE_FIDUCIARIES` deja explícito que **el universo puntuable es 4, no 5** —
      dato que la regla de N chico del spec necesita (asume 5).
- [x] **El ranking de seguros mezclaba períodos sin avisar (PR #648).** `stale` + `years_behind`
      por fila y `period_end` del panel, en paridad con lo que banca ya hacía. Autoseguro se
      rankeaba con estados de **2020** y Confederación del Canadá con los de **2023**, junto a 33
      aseguradoras de 2024: el motor las degradaba por cobertura, pero su score seguía apareciendo
      comparable de igual a igual.
- [x] **`MODEL_VERSION` 0.2 → 0.3 (PR #648).** Descuido detectado al mergear #647: la
      recalibración cambia scores por metodología y no había subido la versión, que es el
      mecanismo de trazabilidad establecido en el Fix 0. Sin eso, un cambio de banda por
      recalibración se leería como deterioro de la entidad.
- [x] **Frescura y cumplimiento en TODOS los motores (PR #649).** Lo había dejado como pendiente
      para pensiones sin una razón real — por inercia, no por criterio. Al ir a hacerlo aparecieron
      dos cosas que estaban pasando en silencio en el ISARS:
      **SeNaSa (la ARS pública más grande del país) y SEMMA se rankeaban con corte 2026-03** contra
      2026-04 del resto; y **ARS Renacer (0.779) y ARS Dr. Yunén (0.764) incumplen el margen de
      solvencia** (SISALRIL ind. 405, ≥1 = cumple) apareciendo en banda "En vigilancia".
      La marca se factorizó en `shared.indices.freshness.annotate_freshness` en vez de escribirla
      por tercera vez; maneja paneles anuales y mensuales y **no mezcla unidades** (restar "2024"
      contra "2026-04" daría un atraso inventado). El ISF se refactorizó para usarla:
      `years_behind` → `periods_behind` + `period_unit`.
      **Pensiones NO lleva bandera de incumplimiento**: su `solvencia` es `patrimonio/activos`, un
      ratio sin umbral legal. Inventarle un corte sería fabricar una señal regulatoria.

- [x] **DECISIÓN DE PRODUCTO CERRADA: el incumplimiento topea la banda, pero solo por
      SOLVENCIA (PR #650).** Elegida por el dueño 2026-08-07 entre cuatro opciones.
      El capital regulatorio es la condición que define si la entidad puede seguir operando;
      la liquidez fluctúa (Aseguradora Agropecuaria, agrícola, incumple liquidez por
      estacionalidad de siniestros teniendo solvencia 3.22). Sin graduar por materialidad: un
      umbral tipo "solo si está 10% corto" agrega un parámetro arbitrario que habría que
      defender ante un cliente, mientras que "cumple o no cumple" es la definición legal.
      **Efecto hoy: CERO bandas topeadas** — las 5 aseguradoras que incumplen ya están en
      Frágil y las 2 ARS en "En vigilancia". Es una regla preventiva, no una recalificación.
      Va en el MOTOR, no en el router: en el router, la ficha de detalle mostraría otra banda
      que el ranking y reabriría la divergencia cerrada en #644/#645.
      `band_capped` distingue "En vigilancia por su score" de "En vigilancia porque incumple".
      El tope NO altera el `overall_score`: el índice sigue auditable contra sus dimensiones.

## FASE 1 — Motor de dos ejes: banca + fiduciarias (§3.1, §7.3)

- [ ] Módulo nuevo de agregación (no tocar `rating_scale.py` todavía) con Ejecución/Resiliencia por
      re-normalización; sin recalibrar pesos.
- [ ] Bandas de Ejecución §4.1 tal cual (Sobresaliente/Competitiva/Rezagada/Deficiente).
- [ ] Regla de N chico §4.2 en el display (banca N grande; fiduciarias N=5 → posición relativa obligatoria).
- [ ] Cortes por percentil sobre distribución real — **requiere prod** (banca/fiduciarias). Si no hay
      acceso: dejar el script listo, sin ejecutar. No simular con fixture.
- [ ] Gate de correlación §8 por sector.
- [ ] Fijar el docstring stale de `fiduciaria.py` (cita pesos v1 35/20/25/10/10 vs. `weights.py` real).

## CALIBRACIÓN FINAL — una sola pasada al cierre (decisión del dueño, 2026-08-07)

> Se difiere A PROPÓSITO, no por inercia: hoy se tocaron cuatro motores y calibrar sobre una
> base que todavía se está moviendo obliga a recalibrar dos veces y publica un vaivén sin
> significado. Se hace una vez, al final, sobre todo lo tocado. **Esta lista es el inventario
> completo de lo que quedó sin calibrar** — si algo no está acá, se pierde.

- [ ] **`cambiaria.py`** — umbrales v1 declarados como calibratables por el propio módulo.
      42 de 92 entidades; explican casi todo el 59% de Resiliencia en "Sólida". Diagnóstico
      hecho: `_calidad_activos` satura con 70% de activos líquidos, `_exposicion_credito` con
      cero cartera.
- [ ] **`fiduciaria.py`** — mismos umbrales v1 declarados como calibratables. N=4.
- [ ] **Los otros 4 sub-componentes de banca** (calidad, eficiencia, liquidez, diversificación).
      Hoy solo se recalibró SOLIDEZ; los demás no se auditaron y pueden tener el mismo defecto
      de techos alcanzables. Medir saturación con el mismo método.
- [ ] **Cortes de banda de Ejecución** — hoy son cuartiles del panel. Validar contra varios
      cortes temporales: un cuartil que se mueve cada trimestre hace que una entidad cambie de
      banda sin cambiar de desempeño.
- [ ] **Bandas de Resiliencia (75/60/45)** — heredadas del ISF sin validar contra la escala de
      banca. Tras el fix de solidez la mediana quedó en 78.1, o sea la mitad del sistema sobre
      el corte de "Sólida". Revisar si los cortes calzan o si conviene otro anclaje.
- [ ] **Cortes de `RATING_SCALE`** — fijados para una escala saturada. Si Perfil SDQ reemplaza
      la notación de letras (§9), puede que no haga falta tocarlos; decidir explícitamente en
      vez de dejarlo implícito.
- [ ] **Anclajes del ISF** — recalibrados hoy contra 33 aseguradoras de UN corte (2024).
      Re-verificar contra el histórico 2018-2024 ya cargado.
- [ ] **Umbral `_MIN_N = 12`** de `robust_bounds` y del panel propio de Ejecución. Elegido por
      criterio ("≈3 observaciones por cuadrante"), no medido. Validar.

## FASE 2 — Seguros (§5)

- [ ] **2a.** Extractor por ramo (§5.6) — exponer los 15+8 ramos, no solo el total.
- [ ] **2b.** Ejecución = combined ratio (loss + expense), ancla 100%, promedio 3-5 años (ingesta ya
      existe, §0.6).
- [ ] **2c.** Reaseguro como dimensión de Resiliencia, scoring en U invertida; Escala sale.
      Banda "sana" a calibrar con la distribución real de las 33, no inventada.
- [ ] **2d.** Siniestros incurridos ≈ pagados + Δreservas (§5.3), con la limitación declarada.
- [ ] **2e.** Gates: peso×dispersión (§5.8), estabilidad de ranking, correlación (§8), cortes por
      percentil. **Todos corribles en local** desde el Excel público.
- [ ] **2f.** Documentar los pesos 35/20/15/15/15 como juicio experto (§5.7) en la superficie de
      metodología visible al cliente.

## FASE 3 — Pensiones (§6)

- [ ] Confirmar cobertura de `patrimonio`/`activos_totales` en `pension_series` — **requiere prod**.
- [ ] Mapeo §6.5; Escala fuera de Resiliencia; N=7 → posición relativa obligatoria.

## FASE 4 — Migración de superficie

- [ ] 47 archivos / 252 ocurrencias de notación de letras (§0.1).
- [ ] Remapeo de `rating_results` / `rating_actions` — **decisión del dueño pendiente** (§9):
      re-etiquetar el histórico vs. corte de fecha.
- [ ] Plan de reissue del Deep Dive de Banco Popular (§10.6).

---

## Decisiones que necesito del dueño antes de arrancar

1. **¿Luz verde al Fix 0?** Toca scores publicados de 33 aseguradoras.
2. **Expense ratio por selección explícita de cuentas** (§0.3) — corrige el §5.2 del spec. ¿Se acepta?
3. **§9 histórico:** ¿re-etiquetar `rating_actions` o corte de fecha?
4. **Acceso a prod** para los gates de banca/fiduciarias/pensiones, o los dejo listos sin correr.
