# Spec — `esg_climate` (Eje 7: ESG & clima)

> Estado: **nuevo (emergente)** · Fase: 4 · v1 2026-05-28 · Doctrina de Casa v1 §9

## 1. Propósito
Riesgo climático y ESG como **riesgo financiero y de mercado**, no solo cumplimiento.
Exposición material por sector; evitar greenwashing (materialidad > narrativa).

## 2. Fuentes (vía `shared/data`)
ONE estadísticas ambientales y de cambio climático; informes IPCC; marcos TCFD/ISSB/SASB.

## 3. Índices
Exposición climática por sector (Nordhaus DICE: costo social del carbono/escenarios; Stern;
Dasgupta capital natural). Métricas ESG estructuradas según **TCFD/ISSB**. Ajuste a
vulnerabilidad del Caribe (huracanes, zona costera).

## 4. Modelo de datos
`EnvIndicator` (tema, período, valor, fuente/linaje), `ESGScore` (exposición + materialidad). PK UUID.

## 5. API — `/api/v1/esg-climate`
`GET /indicators` · `GET /exposure?sector=` · `GET /score`.

## 6. Eventos
- **Publica** `esg.updated`.

## 7. Doctrina codificada (§9)
Materialidad financiera > cumplimiento formal; exigir métrica (penalizar greenwashing);
ajustar a vulnerabilidad climática local.

## 8. Criterios de aceptación
- Tests de exposición/materialidad; cobertura ≥80%.

## 9. Límites / dependencias
Data ambiental local limitada; no es certificación ESG ni auditoría de cumplimiento. Eje emergente.
