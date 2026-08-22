# Spec — `banking_score` (Eje 1: Financiero & riesgo de entidad)

> Estado: **existente** (rating de bancos múltiples) → **extender a todo el universo SIB**
> Fase: 0 (hecho) + 1 (extensión) · v1 2026-05-28 · Doctrina de Casa v1 §3

## 1. Propósito
Score de entidad financiera explicable y auditable. Hoy cubre bancos múltiples; se
generaliza a un **Financial Entity Score** para todo el universo supervisado por la SIB.

## 2. Fuentes de datos (vía `shared/data`)
- `sib_client` — estados financieros por entidad (SIMBAD + APIs SIB), benchmarks sectoriales, límites regulatorios.
- Tipos de entidad a cubrir: bancos múltiples (hecho), **bancos de ahorro y crédito, corporaciones de crédito, asociaciones de ahorros y préstamos (AAyP)**; luego intermediación cambiaria y fiduciarias (submodelos).

## 3. Índice — definición
- 19–21 indicadores en **5 subcomponentes**: solidez 40% · calidad 30% · eficiencia 15% · liquidez 10% · diversificación 5%.
- Lectura: **Perfil SDQ**, dos ejes independientes 0–100 —**Resiliencia** (solidez, calidad,
  liquidez, diversificación; bandas ABSOLUTAS 75/60/45) y **Ejecución** (eficiencia; bandas
  RELATIVAS por cuartil del panel de su tipo de entidad)—. No se resumen en un símbolo único.
  La escala de letras `SDQ-AAA…SDQ-D` está RETIRADA (ver `docs/SPEC_PERFIL_SDQ_TAXONOMIA.md`);
  la columna sobrevive en la base como linaje del dato, no como superficie publicable.
- **Recalibración de pesos por `entity_type`** (las AAyP intensivas en hipoteca; corporaciones de crédito más pequeñas). Mismo marco, distinta calibración — no reconstruir.
- Núcleo determinista; ML (XGBoost) como complemento **explicable** (contribuciones por variable), no oráculo.

## 4. Modelo de datos
- Generalizar `Bank` → soportar `entity_type` enum (`banca_multiple`, `banco_ahorro_credito`, `corporacion_credito`, `aap`, `cambiaria`, `fiduciaria`).
- `BankingData` (1 fila = 1 entidad × período), `RatingResult`, `RatingAction`, `Report`. PK UUID.

## 5. API — prefijo `/api/v1/banking-score`
- Existente: `POST /{entity_id}/run`, scoring, data, reports, model.
- Añadir filtro/parámetro `entity_type` y perfiles de peso por tipo.

## 6. Eventos
- **Publica** `rating.completed`.
- **Consume** `irmp.updated` → ajusta **outlook** (estable/negativo/positivo), no el score intrínseco.

## 7. Doctrina codificada (§3)
- A través del ciclo > punto puntual; penalizar crecimiento rápido de cartera (Minsky); mínimos regulatorios = pisos, no metas.

## 8. Criterios de aceptación
- Tests por tipo de entidad; cobertura ≥80% en `scoring/`.
- Validación: backtesting contra desenlaces (migraciones/defaults) cuando exista histórico etiquetado.

## 9. Dependencias de construcción
- Requiere `shared/data/sib_client` (existe, ampliar) y captura de desenlaces (Fase 1).
