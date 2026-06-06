# Spec — `sector_intel` (Eje 3: Sectorial & de mercado)

> Estado: **nuevo** · Fase: 3 · v1 2026-05-28 · Doctrina de Casa v1 §5(sectorial→§3 canon)

## 1. Propósito
Atractivo y potencial por sector: **IAI** (Investment Attractiveness Index) y **SGPS**
(Sector Growth Potential Score), explicables. Arrancar con 2–3 sectores ancla RD
(Turismo, Energía/Construcción) antes de abrir los 16.

## 2. Fuentes (vía `shared/data`)
ONE (sectorial/social), BCRD (macro/externo), estadísticas sectoriales, World Bank/IMF.

## 3. Índices
- **IAI** — 5 dimensiones: Macro 25% · Negocios 25% · Talento 20% · Regulación 15% · Sector 15%.
  Pesos **por sector** según la matriz de la spec v2 (recalibrables).
- **SGPS** — Histórico 40% · Estructural 35% · Aceleración 25%. La Aceleración usa señales de
  `macro.updated` e `irmp.updated`.
- Marcos: Porter (cinco fuerzas/diamante/HHI), Hausmann-Hidalgo (complejidad), Christensen (disrupción).

## 4. Modelo de datos
`Sector`, `SectorScore` (IAI/SGPS + breakdown), `SectorVariable`. PK UUID.

## 5. API — `/api/v1/sector-intel`
`GET /sectors` · `POST /iai` · `POST /sgps` · `GET /weights`.

## 6. Eventos
- **Consume** `macro.updated`, `irmp.updated`, `trade.updated`. **Publica** `sector.updated`.

## 7. Doctrina codificada
Potencial estructural > tamaño actual; penalizar hype mediático sin fundamento; ajustar
benchmarks globales a la realidad RD/Caribe (Prebisch).

## 8. Criterios de aceptación
- Tests de IAI/SGPS por sector ancla; sensibilidad de pesos; cobertura ≥80%.

## 9. Dependencias
`shared/indices`, `macro_monitor`, `macro_political_risk`. No es estudio de mercado primario.
