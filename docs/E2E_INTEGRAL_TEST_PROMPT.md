# Prompt — Prueba E2E Integral de SDQ·MIP (funcionalidad + contenido + cobertura)

> **Procedencia.** Rescatado el 2026-08-20 de un stash sin commitear del 2026-07-08
> (`WIP on feat/paypal-self-serve-frontend`), donde estaba como archivo NO RASTREADO — nunca
> llegó a `main`. **El documento va tal cual se escribió, sin editar.**
>
> **Tiene seis semanas y la plataforma se movió mucho desde entonces**: el catálogo pasó de
> 14 a 16 ejes, entraron el eje de leyes y el de desarrollo social, y todo el canal de
> alertas (`shared/alerts`) no existía. Los pisos de riqueza por tier y la lista de
> superficies de §4 hay que releerlos contra el catálogo vigente
> (`shared/products/registry.py::PRODUCT_CATALOG`) antes de correrlo, o la auditoría va a
> reportar como completo lo que ni siquiera miró.
>
> No confundir con `E2E_PAYMENTS_PAYPAL_TEST_PROMPT.md`, que cubre solo el cobro.

---

> Pega este documento completo como primer mensaje de una sesión de Claude Code sobre el
> repo `sdq-market-intelligence`. Está escrito para ejecutarse de forma autónoma con
> puntos de control explícitos hacia el dueño.

---

## 0. Misión

Ejecuta una **prueba integral de extremo a extremo de TODA la plataforma SDQ·MIP en
producción**, con la cuenta `claude@sdqconsulting.com.do`. No es solo una prueba de que
"la funcionalidad prende": es una auditoría simultánea de **cuatro dimensiones** en cada
superficie:

- **(A) Funcionalidad** — la característica opera de punta a punta sin errores.
- **(B) Calidad del contenido — en dos capas que se miden por separado:**
  - **(B1) Correctitud / veracidad** — el dato/insight/narrativa es correcto, sin
    alucinación, con cifras que cuadran contra la fuente, y con el tono estándar SDQ
    (advisory, español neutro corporativo, sin anglicismos casuales).
  - **(B2) Adecuación al nivel — "¿esto representa el producto que pensamos vender?"**
    Un reporte puede ser 100% correcto y aun así ser **pobre**: poca profundidad temporal,
    pocos países/entidades comparados, narrativa repetitiva, secciones huecas, dato viejo.
    **Cada tier y cada producto tiene un piso de riqueza esperado** (§4.0). Si el output
    live queda por debajo de ese piso, **es un hallazgo aunque no haya ningún error**, y se
    trata como los demás (§3). No basta con "prende y cuadra": debe estar a la altura del
    nivel que se cobra.
- **(C) Cobertura y alcance** — ¿el dato cubre todo lo que debería (entidades, periodos,
  series, sectores)? Si la fuente **puede extenderse** (más histórico, más entidades, una
  fuente adicional identificable), **levanta el punto y resuélvelo en el momento**.
- **(D) Resolución en el momento** — todo hallazgo se arregla dentro de esta corrida (ver
  §3 para la política de arreglo/PR/aprobación).

**Estado final esperado:** las únicas brechas que pueden quedar abiertas al cierre son
**(i) legales** (permisos/derechos de uso de una fuente) o **(ii) servicios pendientes de
contratar** (un proveedor de pago, una API con licencia, un SKU sin precio fijado).
Cualquier otra brecha —técnica, de datos, de cobertura extensible, de calidad— se resuelve.

---

## 1. Entorno y credenciales

- **Recorrido:** producción en vivo (Railway). Frontend y API de prod.
- **Cuentas de verificación:**
  - `claude@sdqconsulting.com.do` / `Claude1234` — **admin** (dispara syncs y refresh:
    `POST /macro-monitor/refresh`, `POST /pension-intel/sync`, operaciones, admin de
    tarifario/usuarios). Es **free**, así que **no** ve `deep_dive`.
  - `reporting-qa@sdqconsulting.com.do` / `Reporting1234` — **enterprise/viewer**, para
    probar `deep_dive` y superficies de cliente de pago.
  - Usa la cuenta correcta según lo que estés probando; muchos hallazgos de "no se ve el
    deep dive" son en realidad la cuenta free.
- **Arreglos:** se implementan en **local/dev** (backend raíz + DB dev; verificación
  visual vía `preview_start` con el proxy Vite contra prod cuando aplique). Intérprete
  Python: `/opt/anaconda3/bin/python` (3.13), nunca el del sistema.
- **Paridad dev↔prod:** valida que los fixes no rompan en Postgres (VARCHAR, autoflush,
  rollback) aunque pasen en SQLite.

---

## 2. Reglas de operación (no negociables)

1. **Verifica cada superficie, no extrapoles de una muestra.** Si un módulo tiene 7
   entidades, revisa las 7, no 1. Si un producto tiene 3 tiers × N sectores, muestrea a lo
   ancho, no un solo caso.
2. **Excelencia sobre velocidad.** No enmascares síntomas ni des por bueno un "parece que
   sí". Si algo se ve raro, indágalo a fondo antes de declararlo OK o de arreglarlo.
3. **"IA para interpretar, nunca para contar".** Cualquier cifra en narrativa debe tener
   respaldo determinista; marca como hallazgo toda cifra generada por IA sin numeric_guard.
4. **Tono:** valida contra `REGISTER_NEUTRO` (cerebro.py, fuente única). Cero anglicismos
   casuales (upside/downside/alpha/timing/pipeline); conserva técnicos (Sharpe/spread/rating).
   Caveats en tono advisory, no warning.
5. **El dueño es no técnico:** tú ejecutas todos los pasos técnicos; no le pidas correr comandos.

---

## 3. Política de resolución de hallazgos

Para **cada** hallazgo que requiera cambio de código:

1. **Investiga la causa raíz** (sin adivinar). Identifica el archivo/función.
2. **Implementa el arreglo** en local/dev y **verifícalo** (la superficie afectada + la
   regresión obvia). Si es de datos/cobertura, corre el sync/backfill correspondiente y
   confirma el dato nuevo.
3. **Abre un PR** por hallazgo (o por lote coherente), con descripción de causa→fix→verificación.
4. **DETENTE antes de mergear.** No hagas `merge --no-ff` a `main` ni despliegues a prod
   sin el OK explícito del dueño. Presenta el PR y espera aprobación.
5. Los hallazgos **sin código** (dato desactualizado que solo requiere correr un sync ya
   existente, un caveat, una serie a re-ingerir) sí se resuelven en el momento y se reportan.

> Hallazgos que NO se arreglan y solo se documentan: los **legales** (derecho de uso de una
> fuente) y los de **servicio pendiente de contratar** (proveedor de pago, API licenciada,
> SKU sin precio). Todo lo demás se resuelve o se abre PR.

---

## 4.0 Rúbrica de adecuación por nivel (piso de riqueza — dimensión B2)

Antes del recorrido, ancla el **piso de riqueza** que cada salida debe cumplir para ser
vendible. Mide **cada reporte, en cada tier, contra el piso de su nivel**. Quedar por
debajo = hallazgo, aunque las cifras sean correctas.

**Ejes de adecuación (los 4 que revientan primero):**

1. **Profundidad temporal (periodos).** ¿Hay trayectoria/tendencia, o es una foto de un
   solo corte? Un producto serio muestra la evolución del score y de sus dimensiones en el
   tiempo (banca y pensiones ya tienen trayectoria + percentil; el resto debe alcanzar
   paridad). Una sola fecha = pobre.
2. **Amplitud comparada (países/entidades/panel).** Si el índice se sostiene sobre un panel
   (ej. IRMP = 24 países; ISA = 7 AFP; banca = N entidades), el reporte **debe** ubicar al
   sujeto dentro de ese panel (rango, percentil, distancia al líder/media). Una sección
   "Posición en el Panel" que dice *"no puede cuantificarse con los datos disponibles"*
   teniendo el panel disponible = hallazgo, no limitación honesta.
3. **Riqueza y no-redundancia del contenido.** ¿Cuántos factores/sub-indicadores con dato
   real sostienen el análisis? ¿La narrativa profundiza o repite la misma tesis sección
   tras sección? ¿Hay drill-down, escenarios/sensibilidades, señales de revisión
   accionables — o solo la lectura plana del score? Repetición y conteo bajo de factores =
   pobre.
4. **Frescura.** ¿Qué antigüedad tiene el dato más reciente? Un dato de ~190 días en un
   producto macro que se vende como inteligencia de mercado está por debajo del piso; cruza
   con la auditoría de frescura (§4.9) y con la cadencia real de la fuente.

**Escalera por tier (el piso sube con el precio):**
- **Pulse** — foto correcta + una lectura. Aun así: dato fresco y al menos una comparación
  o contexto, no solo el número.
- **Insight** — lo de Pulse **+ trayectoria + posición en panel + 2 secciones que
  profundizan** (escalera de valor Insight 1→2 secciones). Si un "Insight" no tiene
  trayectoria ni panel, no es Insight.
- **Deep Dive** — lo de Insight **+ drill-down a sub-indicadores + escenarios/sensibilidades
  + Entorno Operativo + alerta temprana donde aplique**. Debe leerse como un informe tier-1.

> **Regla:** para cada producto pregunta *"si yo pagara por esto, ¿lo sentiría completo?"*.
> Si la respuesta es no, el porqué (poca historia / poca amplitud / contenido delgado /
> dato viejo) es el hallazgo. Ver el **Apéndice A** para un ejemplo trabajado real.

**El lente B2 aplica a TODA superficie que genere información — no solo a los descargables.**
En cada punto del sistema donde se produce un texto/insight/score interpretado, corre el
mismo cuestionamiento de §4.0. Inventario mínimo a cubrir (por módulo de §4):

- **Reportes descargables** — Pulse / Insight / Deep Dive, en las 3 salidas (online · PDF ·
  Word), por sector y por país/entidad.
- **Insight IA al hacer click en un indicador** — el `AiInsightCard` / drawer del drill-down
  (patrón dos fases). Este es el caso que a menudo se olvida: al abrir un indicador, el
  insight que se genera **debe** tener profundidad (no una frase plana), apoyarse en dato
  real con numeric_guard, comparar/contextualizar y no repetir el título. Un insight de
  indicador de una sola línea genérica = hallazgo B2.
- **Tarjetas de insight de tablero** — las cards de resumen por eje/sector en los dashboards
  (banca, pensiones, macro, sectorial, ESG, gobernanza).
- **Pulsos nacionales / por-entidad** — el pulso que se muestra en pantalla antes de cualquier
  descarga.
- **Secciones narrativas vivas** — AI Insights veredicto-primero, Entorno Operativo, Alerta
  Temprana (banca y pensiones), evaluación IA del producto de Política Monetaria.
- **Comparador / Market Brief / Deal Scoring** — cualquier salida interpretada que exhiban.

Regla operativa: **si una pantalla muestra una oración generada, esa oración pasa por B1 y
B2.** No declares "OK" un módulo hasta haber abierto sus insights de indicador uno por uno
(no extrapolar de uno — §2, regla 1).

---

## 4. Alcance — recorrido módulo por módulo

Para cada módulo, evalúa las 4 dimensiones (A funcionalidad / B1 correctitud / B2 adecuación
al nivel / C cobertura / D resolución). Preguntas guía por módulo:

### 4.1 Banking Score (Eje 1)
- ¿Cargan los 19 indicadores y la escala de 10 tiers para **todas** las corporaciones?
- Drill-down + IA del indicador (dos fases, AiInsightCard/drawer): ¿el insight cuadra con el dato?
- **Cobertura:** ¿están todas las entidades de banca múltiple + captadoras de depósitos?
  ¿Falta alguna corporación por auto-registrar (corrida limpia SIB)? ¿Clasificaciones
  correctas (ej. ADEMI, Bonao≠Bonanza)?
- Alerta Temprana (7 señales precursoras crisis 2003): motor + sección deep dive + panel.

### 4.2 Macro Monitor + Modelo TPM
- Series BCRD live (25+ MacroSeries): frescura y cuadre. IMAE base 2018.
- Modelo TPM: `/comunicados/forecast`, `/model/backtest`, track-record en vivo
  (`/comunicados/forecast/track-record`). ¿El pronóstico y el backtest exhiben cifras reales?
- Publicaciones BCRD: IPoM (patrón nuevo trimestral `IPoM-{mes}-{año}`), y los otros 2
  informes. **Cobertura:** ¿la ingesta de publicaciones está agendada y fresca? ¿Se captan
  comunicados/notas de prensa (hoy NO)? ¿Se puede cerrar esa brecha?

### 4.3 Pension Intel (SIPEN)
- Pulse nacional + ISA por AFP (7 AFP). Estados financieros auditados live (OCR→Claude).
- 5 dimensiones incl. riesgo (σ del NAV, Sharpe). Rentabilidad REAL deflactada.
- Alerta Temprana pensiones (paridad con banca). **Cobertura:** composición de cartera
  (dato SIPEN sin usar), series live completas.

### 4.4 Sectorial (Eje 3), Social (Eje 6), Comercio, Energía, Telecom
- IAI real por sector; Gate E backtests. Comercio=DGA real; Social=IDM real; Telecom=ITU.
- ENAE/ONE cableado al IAI y Gate E (había PRs pendientes: verificar estado).
- **Cobertura:** ¿algún sector con dato vacío que tenga fuente disponible identificable?

### 4.5 ESG / IRC nacional (Eje 7) + Gobernanza (Eje 4 IRMP)
- IRC nacional + panel Caribe (RD IRC ~35.65). WGI vigentes (RL/GOV_WGI_*). IRMP panel 24 países.

### 4.6 Seguros (F0 — en descubrimiento)
- Estado del descubrimiento (GO). Marca explícitamente qué está **incompleto por diseño**
  (spike REDATAM SISALRIL, plan F1 sin aprobar) vs. lo que ya se puede extraer (CKAN
  primas, Power BI publish-to-web solvencia). NO forzar integración; documentar el estado
  y qué falta contratar/aprobar.

### 4.7 Deal Scoring
- Rúbrica 7 ejes + lazo de cosecha. Marca las ~98 entradas "open" que esperan **input del
  dueño** (esa es brecha de negocio, no técnica) vs. defectos técnicos reales.

### 4.8 Productos / Monetización (transversal — cara al cliente de pago)
- **Catálogo multipaís:** Banca=entidad, Macro/ESG=país, 7 nacionales fijos. Pantalla de
  parámetros y descarga.
- **Reportes por sector y tiers** (`/api/v1/products/{sector}/{tier}/report`): pulse /
  insight / deep_dive. Escalera de valor (Insight 1→2 secciones). Producto Política
  Monetaria (3 tiers) con evaluación IA + trayectoria + pronóstico/backtest/track record.
- **3 salidas** (online · PDF · Word) con marca + secciones Metodología/Fuentes auto.
  Verifica que las tres cuadren entre sí (paridad web↔PDF↔Word) y con el dato live.
- **Tarifario (admin) + Mi Plan + suscripción gestionada por admin** (Fase 1/2 recientes).
  Prueba el flujo completo. **Brecha conocida:** SKU `deep_dive:monetary_policy` sin precio
  en prod → esto es "servicio/precio pendiente", documéntalo (no es defecto técnico).
- **Alertas** y acceso por tier/RBAC.

### 4.9 Transversales
- **RBAC:** super_admin/admin/analyst/viewer + tier; CRUD de usuarios gateado; que free no
  vea deep_dive, que enterprise sí.
- **i18n:** UI ES/EN/FR completa; muestrea cambios de idioma en superficies clave.
- **Conectores / frescura de datos:** recorre la auditoría de frescura
  (`data-freshness-audit`); todo sync debe estar agendado y con dato reciente. Cualquier
  fuente caída (como el IPoM en su momento) se detecta aquí.

---

## 5. Registro de hallazgos (durante la corrida)

Lleva una tabla viva. Por hallazgo:

| # | Módulo | Dimensión (A/B/C/D) | Severidad | Descripción | Causa raíz | Acción tomada | Estado (Resuelto / PR abierto / Brecha legal / Brecha servicio) |

Severidad: Crítico (bloquea cliente) · Alto · Medio · Bajo/cosmético.

---

## 6. Informe final (entregable)

Al terminar el recorrido, entrega un informe en español con:

1. **Resumen ejecutivo:** salud global de la plataforma en una línea por dimensión.
2. **Tabla de hallazgos** completa (§5) con su resolución.
3. **PRs abiertos** esperando aprobación (lista con enlaces), agrupados por prioridad de merge.
4. **Cobertura resuelta:** fuentes extendidas / series backfilleadas / entidades agregadas
   en el momento.
5. **Brechas remanentes — SOLO estas dos categorías:**
   - **Legales:** derecho/permiso de uso de una fuente.
   - **Servicios pendientes de contratar:** proveedor de pago, API licenciada, SKU sin
     precio, plan de sector sin aprobar.
   Si algo no cae en estas dos categorías, no debería estar "pendiente": vuelve y resuélvelo.
6. **Recomendación de despliegue:** qué PRs mergear primero y en qué orden para dejar prod
   en su mejor estado.

---

## 7. Definición de "terminado"

- Cada módulo de §4 recorrido en las 4 dimensiones, **verificado en prod** (no extrapolado).
- Cada hallazgo técnico/de datos/de cobertura/de **adecuación (B2)**: resuelto o con PR
  abierto esperando OK.
- Informe §6 entregado.
- Las únicas líneas abiertas son legales o de servicio por contratar, explícitamente etiquetadas.

---

## Apéndice A — Ejemplo trabajado: por qué un reporte correcto puede ser "pobre"

**Caso real:** `Insight Riesgo-País · República Dominicana` (IRMP 48.7 · Elevado,
período 2024-12-31). Es **funcionalmente correcto y las cifras cuadran (A y B1 pasan)** —
y aun así **NO representa el producto que se pretende vender**. Falla en **B2 (adecuación)**
en los cuatro ejes de §4.0:

1. **Profundidad temporal — FALLA.** Es una sola foto (2024-12-31). Cero trayectoria del
   IRMP o de sus 5 dimensiones. Banca/pensiones ya tienen trayectoria+percentil; este
   producto macro quedó atrás. → *Arreglo esperado: llevar el Insight/Deep de macro a
   paridad con la trayectoria de banca/pensiones.*
2. **Amplitud comparada — FALLA GRAVE.** La sección "2. Posición en el Panel Regional"
   dice: *"no puede cuantificarse con los datos disponibles… no se emite un juicio de rango
   relativo"* — pero **el IRMP se sostiene sobre un panel de 24 países**. El producto no usa
   su propio activo comparativo. → *Arreglo esperado: cablear percentil/rango de RD dentro
   del panel de 24 al payload del reporte.*
3. **Riqueza — FALLA.** Solo "6 factores con dato"; secciones 1 y 2 repiten la misma tesis
   (vulnerabilidad externa define el riesgo) sin agregar profundidad; sin drill-down a
   sub-indicadores, sin escenarios. → *Arreglo esperado: más factores con dato real y/o
   desagregación; eliminar redundancia entre secciones.*
4. **Frescura — FALLA.** "El dato más reciente tiene 190 días" (~6 meses) en un producto de
   inteligencia de mercado. → *Arreglo esperado: verificar cadencia real de las fuentes
   (BCRD/DIGEPRES/WGI/GDELT) y refrescar; si una fuente no publica más seguido, decirlo como
   límite real, no dejar el dato viejo silencioso.*

**Lección para el ejecutor:** cuando un reporte "pase" en A y B1, **no lo declares OK sin
correr el checklist de §4.0**. La pregunta que destapa estos casos es *"¿lo sentiría
completo si pagara por esto?"*. Aplica este mismo lente a **todos** los productos/tiers de
§4.8, no solo al macro — este es el patrón, no la excepción.
