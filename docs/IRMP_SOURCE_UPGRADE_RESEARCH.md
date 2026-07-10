# IRMP — Investigación de fuentes para llevar el producto a nivel tier-1

**Fecha:** 2026-07-10 · **Autor:** análisis de datos SDQ·MIP · **Producto:** SDQ Macro & Country Risk (IRMP, Eje 4)

**Motivación:** el Deep Dive de riesgo-país sale hoy con un solo corte y un panel
de 5 países, y — más grave — **3 de sus 5 dimensiones se alimentan de "rúbrica"
tecleada a mano** en `shared/doctrine/regulatory.yaml`, no de dato vivo. Un
comprador que audite la metodología encontraría que "incertidumbre electoral = 30"
para RD está simplemente escrito. Esto documenta con qué fuentes reales se cierra
esa brecha.

---

## 1. Diagnóstico: dónde está la delgadez (por variable)

El IRMP tiene 5 dimensiones (pesos entre paréntesis). Estado real de cada input:

| Dimensión | Variable | Fuente HOY | ¿Dato vivo? |
|---|---|---|---|
| **macro** (0.30) | gdp_cagr_3y, inflation_gap, fiscal_balance_gdp, public_debt_gdp, reserves_import_months | WDI / IMF WEO / BCRD | ✅ real |
| **external** (0.20) | current_account_gdp, fdi_gdp, fx_volatility | WDI / IMF | ✅ real |
| | sovereign_rating_score | scrape Wikipedia (S&P) | 🟡 real pero no autoritativo |
| **political** (0.25) | wgi_rule_of_law, wgi_gov_effectiveness, wgi_control_corruption, wgi_political_stability, wgi_voice_accountability | WGI API `mrv=1` (percentil viejo, 1 año, 5 países) | 🟡 real pero mínimo |
| | **electoral_uncertainty, policy_continuity** | **rúbrica YAML** | ❌ tecleado |
| **regulatory** (0.15) | wgi_regulatory_quality | WGI API `mrv=1` | 🟡 mínimo |
| | **regulatory_volatility_5y, discretion, contract_enforcement** | **rúbrica YAML** | ❌ tecleado |
| **events** (0.10) | **news_sentiment, unrest_shocks, sanctions_signal** | **rúbrica YAML** (GDELT planeado, no cableado) | ❌ tecleado |

**Resumen:** ~8 de ~25 variables son rúbrica tecleada; la gobernanza usa el mínimo
del WGI (un año, percentil relativo viejo); solo macro/external están sólidas.

---

## 2. Hallazgo central: la revisión **WGI 2025** es un salto estructural

El Banco Mundial publicó (dic-2025) la **revisión metodológica WGI 2025**, con
dataset descargable (`wgidataset_with_sourcedata-2025.xlsx`). Cambia el juego:

1. **Escala absoluta 0–100** anclada a países benchmark fijos. Antes el WGI era
   percentil/z-score *relativo*, por lo que el número de RD se movía si cambiaba
   el panel. Con la escala absoluta, el score es **estable y comparable en el
   tiempo y entre países** → resuelve de raíz la tensión "ampliar el panel mueve
   el número".
2. **Serie recalculada 1996–2024** consistente → **29 años de trayectoria real**
   por dimensión (no 1 corte, no snapshots de prueba).
3. **35 fuentes subyacentes por país/año** en el dataset (columnas por fuente:
   ADB, AFR, BTI, EIU, GWP, PRS, WJP, VDM, WMO, …) + **número de fuentes** +
   **error estándar** + **intervalo de confianza 90%** sobre el score 0–100.
4. **200+ economías** → el panel puede ser de cualquier tamaño (24, cohorte
   regional, cohorte por ingreso), no 5.

**Verificado sobre RD en el dataset (2024, escala 0–100):**

| Dimensión WGI | Score RD 2024 | # fuentes | Trayectoria disponible |
|---|---|---|---|
| Voice & Accountability | 60.4 | 11 | 1996–2024 |
| Political Stability | 76.0 | 9 | 1996–2024 |
| Government Effectiveness | 52.8 | 8 | 1996–2024 |
| Regulatory Quality | 58.1 | 7 | 1996–2024 |
| Rule of Law | 53.8 | 12 | 1996–2024 |
| Control of Corruption | **42.5** | 10 | 1996–2024 |

Ejemplo de trayectoria real (Rule of Law): **45.6 (2010) → 53.8 (2024)** — una
historia genuina de fortalecimiento institucional que hoy el producto no cuenta.

**Qué habilita en el producto, sin inventar nada:**
- Trayectoria real de 29 años por dimensión de gobernanza.
- **Cuantificación de incertidumbre** (IC 90% + n_fuentes) → señal tier-1 de rigor.
- Panel de cualquier tamaño sobre escala absoluta (sin drift de score).
- **Mata una rúbrica con dato real:** `regulatory_volatility_5y` se calcula como
  la desviación de la serie WGI-RQ de 5 años (RD: σ=1.68 real, deriva +4.7/10a).
- Drill-down "qué fuentes cubren a RD y cuánto discrepan" (las 7–12 por dimensión).

**Licencia:** World Bank Open Data — **CC-BY 4.0** (uso comercial con atribución).
Ya declarada en `shared/data/wgi_client.py`.

**Acción:** reemplazar la ingesta actual (API `mrv=1`, 5 países, percentil viejo)
por la ingesta del **dataset completo 1996–2024 con source data** (escala absoluta
+ IC + n_fuentes + 35 fuentes). Es el cambio de mayor impacto/costo.

---

## 3. Fuentes recomendadas para las rúbricas restantes (political / regulatory / events)

Aun con WGI-2025, quedan variables de juicio hoy tecleadas. Fuentes reales:

### 3.1 V-Dem (Varieties of Democracy) — political + regulatory
- **Qué:** ~500 indicadores de democracia/instituciones, **202 países, 1789–2024**,
  Univ. de Gotemburgo. Series anuales, metodología académica revisada.
- **Cierra:** `electoral_uncertainty` (índices de elecciones libres/justas, *electoral
  democracy index*), `policy_continuity` y `discretion` (*rule of law index*,
  *judicial/legislative constraints on the executive*).
- **Acceso:** descarga académica del dataset v15; API/CSV. **Licencia a verificar**
  para uso comercial (V-Dem es libre para investigación; el uso en producto pagado
  requiere confirmar términos — flag legal).

### 3.2 GDELT — events (ya hay conector, falta cablear)
- **Qué:** eventos globales en tiempo real; tono de prensa (`news_sentiment`) e
  intensidad de protesta/inestabilidad (`unrest_shocks`, vía códigos CAMEO).
- **Cierra:** toda la dimensión `events`. **El conector ya existe**
  (`gdelt_sync.py`, `gdelt_bq_sync.py`) — falta enchufarlo al ensamblado en vez
  del fallback rúbrica (era el pendiente "T8").
- **Acceso:** BigQuery público / API. Gratis. **Vía AI-native** del producto.

### 3.3 WJP Rule of Law Index — regulatory (contract_enforcement, discretion)
- **Qué:** 8 factores (justicia civil, cumplimiento regulatorio, límites al poder),
  ~142 países, anual. **Ya es una de las 35 fuentes del WGI** (código WJP).
- **Cierra:** `contract_enforcement`, `discretion` con sub-factores explícitos.
- **Acceso:** descarga pública con atribución.

### 3.4 Fraser / Heritage Economic Freedom — regulatory (respaldo)
- **Qué:** libertad económica; sub-índices de propiedad, regulación, integridad
  del gobierno. **Heritage (HER) ya es fuente WGI.** Anual, ~165 países.
- **Cierra:** respaldo cruzado a `discretion` / calidad regulatoria.
- **Acceso:** descarga pública.

### 3.5 World Bank B-READY (Business Ready) — regulatory (contract_enforcement)
- **Qué:** sucesor de Doing Business (2024+); marco regulatorio + servicios
  públicos, incluye resolución de disputas / cumplimiento de contratos.
- **Cierra:** `contract_enforcement` con dato oficial (cobertura creciente).
- **Acceso:** descarga pública WB.

### 3.6 Listas de sanciones (OFAC / UE / ONU) — events (sanctions_signal)
- **Qué:** listas oficiales estructuradas (OFAC SDN, consolidada UE, ONU).
- **Cierra:** `sanctions_signal` con exposición real, no teclada.
- **Acceso:** descargas oficiales estructuradas. Gratis.

### 3.7 Rating soberano — external (upgrade menor)
- **Hoy:** scrape Wikipedia (S&P). Funciona pero no es autoritativo.
- **Mejora:** mantener el scrape como agregador, pero anclar a comunicados
  oficiales de S&P/Fitch/Moody's cuando haya acción de rating (ya semi-hecho vía
  `sovereign-ratings-sync`). Bajo impacto.

---

## 4. Impacto esperado por fase

| Fase | Cambio | Rúbricas que mueren | Se gana |
|---|---|---|---|
| **A** | Ingerir dataset WGI-2025 completo (absoluto + IC + 35 fuentes + 1996–2024) | `regulatory_volatility_5y` | Trayectoria 29a, incertidumbre, panel N, drill-down fuentes, escala estable |
| **B** | Cablear GDELT a `events` | `news_sentiment`, `unrest_shocks` | Señal de corto plazo real, AI-native |
| **C** | V-Dem → political/regulatory | `electoral_uncertainty`, `policy_continuity`, `discretion` | Juicio político con serie académica real |
| **D** | WJP / B-READY → `contract_enforcement`; sanciones → `sanctions_signal` | `contract_enforcement`, `sanctions_signal` | Regulatorio + sanciones con dato oficial |

Al terminar D, **0 de 25 variables serían rúbrica tecleada** (salvo supuestos
declarados legítimos como la meta de inflación por país).

---

## 5. Recomendación de secuencia

1. **Fase A primero** (WGI-2025) — mayor impacto, dato ya en mano, licencia clara,
   resuelve trayectoria + panel + incertidumbre + una rúbrica de una sola vez.
2. **Fase B** (GDELT) — conector ya existe; enchufar y validar.
3. **Fase C** (V-Dem) — condicionada a **verificar licencia comercial** (flag legal).
4. **Fase D** (WJP/B-READY/sanciones) — cierra las rúbricas restantes.

Cada fase: PR propio, verificación en prod, sin mutar scores salvo donde el cambio
de fuente lo justifique explícitamente (y ahí se documenta el antes/después).

**Nota de honestidad de producto:** mientras una variable siga siendo rúbrica, el
reporte debe rotularla como "estimación declarada" y no presentarla como dato de
fuente. La escalera de riqueza (Pulse < Insight < Deep) exige que el Deep Dive, en
particular, no dependa de números tecleados.
