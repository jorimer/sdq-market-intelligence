# Spec — `macro_monitor` (Eje 2: Macroeconómico)

> Estado: **nuevo** · Fase: 2 · v1 2026-05-28 · Doctrina de Casa v1 §4

## 1. Propósito
Monitor de coyuntura y puntos de inflexión sobre datos del BCRD. No compite en precisión de
forecast: detecta **fragilidad temprana** y traduce el entorno en señales para otros ejes.

## 2. Fuentes (vía `shared/data/bcrd_client`)
Sector real (PIB, IMAE), precios (IPC), monetario y financiero, sector externo/balanza de pagos
(remesas, exportaciones, turismo), mercado laboral (ENCFT), encuesta de expectativas.

## 3. Índice(s)
Índices de **momentum** (cambio y aceleración) por serie, con bandas de incertidumbre.
Señales de alerta tipo Reinhart-Rogoff (deuda) y Calvo (freno súbito de flujos). Salidas
**probabilísticas** (Tetlock), nunca punto-estimado seco.

## 4. Modelo de datos
`MacroSeries` (serie, período, valor, fuente, fecha_publicación/linaje), `MacroSnapshot`
(índices de momentum + señales). PK UUID. Datos faltantes = null (sin interpolar).

## 5. API — `/api/v1/macro-monitor`
`GET /indicators` · `GET /snapshot?period=` · `GET /signals`.

## 6. Eventos
- **Publica** `macro.updated` → consumido por `sector_intel` (dimensión Macro) y `macro_political_risk` (dimensión Macro del IRMP).

## 7. Doctrina codificada (§4)
Señal de inflexión > nivel; momentum > nivel absoluto; parte del consenso (BCRD/FocusEconomics)
y marca desviaciones explícitas; declara el rezago de publicación.

## 8. Criterios de aceptación
- Tests de cálculo de momentum/señales ≥80%; manejo de series con huecos.

## 9. Dependencias
`shared/data/bcrd_client`, `shared/indices`. Bloqueante: capa de datos (Fase 1).
