# Spec — `social_dev` (Eje 5: Social & desarrollo)

> Estado: **nuevo** · Fase: 4 · v1 2026-05-28 · Doctrina de Casa v1 §7

## 1. Propósito
Índices de desarrollo, inclusión, género y ODS de forma **multidimensional y basada en
evidencia**. Es el eje que sostiene la credibilidad de think tank y abre clientes de
gobierno, multilaterales y ESG. Atención especial a la **informalidad** (rasgo estructural RD).

## 2. Fuentes (vía `shared/data/one_client`)
ONE: estadísticas demográficas, sociales, género, censos, indicadores ODS; ENHOGAR, ENCFT.
Complementar con inclusión financiera (Findex, SB).

## 3. Índices
Índices de desarrollo/bienestar multidimensional (Sen), pobreza/consumo (Deaton),
informalidad (de Soto), desigualdad/distribución (Piketty). Reportar **distribución, no solo
promedio**. Diseño de indicadores basado en evidencia (Banerjee-Duflo).

## 4. Modelo de datos
`SocialIndicator` (tema, período, valor, desagregación, fuente/linaje), `DevelopmentScore`. PK UUID.

## 5. API — `/api/v1/social-dev`
`GET /indicators` · `GET /index?dimension=` · `GET /sdg`.

## 6. Eventos
- **Publica** `social.updated` (consumido por reports/think-tank publications).

## 7. Doctrina codificada (§7)
Bienestar multidimensional > PIB; distribución > promedio; conducta/registro > percepción declarada.

## 8. Criterios de aceptación
- Tests de índices multidimensionales; manejo de periodicidad censal y huecos; cobertura ≥80%.

## 9. Límites / dependencias
Periodicidad de censos (~10 años) limita oportunidad; orienta, no concluye causalidad (no RCT).
Depende de `shared/data/one_client`.
