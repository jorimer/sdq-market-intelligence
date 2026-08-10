# Spec — `social_dev` (Eje 5: Social & desarrollo)

> Estado: **nuevo** · Fase: 4 · v1 2026-05-28 · Doctrina de Casa v1 §7

## 1. Propósito
Índices de desarrollo, inclusión, género y ODS de forma **multidimensional y basada en
evidencia**. Es el eje que sostiene la credibilidad de think tank y abre clientes de
gobierno, multilaterales y ESG. Atención especial a la **informalidad** (rasgo estructural RD).

## 2. Fuentes
El eje ya **no cuelga de un solo conector**: cada indicador se toma de quien lo produce.

| Dato | Conector | Emisor |
|---|---|---|
| Pobreza general y extrema, por región | `shared/data/one_client` (`ONEClient`) | ONE (CDN de descargas) |
| Informalidad laboral | `shared/data/bcrd_labor` | BCRD (ENCFT) |
| Cobertura educativa, por región y provincia | `shared/data/minerd_coverage` | MINERD (tablero SIIE) |
| Indicadores provinciales del padrón | `shared/data/siuben_client` | SIUBEN |
| Salud e inclusión financiera | `shared/data/wdi_client` | Banco Mundial (WDI/Findex) |
| Ingreso laboral y escolaridad | `shared/data/one_client` | ONE — **hoy caído** (portal tras Cloudflare) |

El portal `www.one.gob.do` responde 403 desde producción; lo que depende de él declara la
falla en `errors` de la operación en vez de devolver cero en silencio.

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
Ver la tabla de fuentes en §2: la dependencia es por indicador, no del módulo entero.
