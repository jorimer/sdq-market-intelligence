# SDQMIP — Especificaciones por módulo (think tank multi-eje)

> Versión v1 · 2026-05-28 · Documento accionable por desarrollo.
> Traduce el **Blueprint v2 (Scope Maestro)**, el **Canon Metodológico** y la
> **Doctrina de Casa v1** a módulos concretos del repo. Estos `.docx` viven en la
> carpeta del proyecto y son la fuente conceptual; estos `SPEC.md` son la fuente de implementación.

## Principio rector (anti-Frankenstein)

Un motor, tres fuentes, múltiples ejes, una arquitectura. Cada eje es un módulo
autocontenido (`api/`, `models/`, `scoring/`, `tests/`) que **reutiliza las capas
compartidas** y se comunica por el `event_bus` — nunca importa de otro módulo ni
accede a sus tablas (ver `CLAUDE.md`).

## Mapa de ejes → módulos

| Eje | Módulo | Estado | Fase | Fuente principal | Doctrina |
|---|---|---|---|---|---|
| 1 Financiero & riesgo de entidad | `banking_score` | existente → extender | 0–1 | SIB | §3 |
| 2 Macroeconómico | `macro_monitor` | nuevo | 2 | BCRD | §4 |
| 3 Sectorial & de mercado | `sector_intel` | nuevo | 3 | ONE/BCRD | §5 |
| 4 Regulatorio & político | `macro_political_risk` | scaffold hecho | 2 | SIB/WGI | §6 |
| 5 Social & desarrollo | `social_dev` | nuevo | 4 | ONE | §7 |
| 6 Comercio exterior & cadena | `trade_intel` | nuevo | 5 | BCRD/DGA | §8 |
| 7 ESG & clima | `esg_climate` | nuevo | 4 | ONE/IPCC | §9 |

## Capas compartidas (`shared/`) — se construyen una vez

- **`shared/data/`** — conectores por fuente (`sib_client`, `bcrd_client`, `one_client`,
  `dgii_client`, `dga_client`), normalización, **linaje** y **captura de desenlaces
  etiquetados**. Verificación de licencia obligatoria antes de ingerir al corpus.
  Regla del proyecto: datos faltantes = `null`, nunca interpolar sin disclosure.
- **`shared/indices/`** — motor de índices explicable reutilizable: normalización
  regional min-max (con inversión para variables risk-increasing), ponderaciones por
  dominio, bandas, contribuciones auditables. Patrón ya probado en `banking_score/scoring`
  y `macro_political_risk/scoring`. **Todo índice nuevo se construye aquí, no se reescribe.**
- **`shared/knowledge/`** — pipeline RAG: `ingest.py` (verificación de licencia + carga),
  `corpus/` (fuentes con derechos + doctrina), `index/` (vectorial), `retrieve.py`.
  Solo fuentes de uso libre/propias (ver Canon §7).
- **`shared/doctrine/`** — doctrina de casa versionada por eje (Capa 3). La doctrina es
  el documento de control: todo cambio de peso se hace primero aquí y de ahí al código.
- **`shared/narrative/`** — motor Claude SCQA (existe); consume `retrieve.py` y la doctrina.

## Mapa de eventos (event_bus)

| Evento | Publica | Consume |
|---|---|---|
| `rating.completed` | banking_score | reports, notifications |
| `irmp.updated` | macro_political_risk | banking_score (overlay outlook), sector_intel |
| `macro.updated` | macro_monitor | sector_intel, macro_political_risk |
| `sector.updated` | sector_intel | reports |
| `trade.updated` | trade_intel | sector_intel (resiliencia/MRS) |

## Regla de trazabilidad (calidad)

Toda afirmación/score emitido debe rastrearse a (a) una variable/regla de la metodología,
(b) un documento del corpus con derechos, o (c) la doctrina de casa versionada. Si no, no se emite.

## Convenciones (de CLAUDE.md)

Identificadores Python en inglés · strings UI/errores de API en español · PK UUID
(`shared.database.base.UUIDMixin`) · prefijo `/api/v1/{module-name}` · tests ≥80% en
lógica de scoring antes de merge · migraciones Alembic (registrar modelos en `env.py`).
