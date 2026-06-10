# Propuesta metodológica — Submodelos Cambiarias y Fiduciarias (SIB)

> Eje 1 (Financiero). Cierra la cobertura del universo supervisado por la SIB.
> Estado: **propuesta para aprobación** (antes de ETL/UI). Fecha: 2026-06-08.

## 0. TL;DR

- **Cambiarias: SÍ se pueden construir.** El SIB publica balance y estado de
  resultados completos para estas entidades vía endpoints **EIC**
  (`estados/situacion/eic`, `estados/resultados/eic`). Universo: **ARC** (6
  agentes de remesas y cambio, materiales) + **AC** (35 agentes de cambio,
  mayoría muy pequeños).
- **Fiduciarias: SÍ se pueden construir** (corrige la conclusión previa, 2026-06-10).
  La **API de estadísticas** del SIB no las expone — pero el **portal de supervisados**
  (`sb.gob.do/supervisados/fiduciarias/<entidad>/`) publica los **estados financieros
  auditados anuales en PDF** por entidad (2020–2025). Los PDF son escaneos **con capa de
  texto OCR ya embebida** (escáner PaperStream) → `pdftotext -layout` extrae balance y
  estado de resultados sin OCR propio (verificado: Reservas 2024, Total activos
  RD$2,031M, Ingresos RD$1,334M). Detalle y plan en §5.
- El motor de scoring **ya tiene perfil de pesos `cambiaria`** definido. Falta:
  (1) ETL de EIC, (2) indicadores propios de intermediación cambiaria,
  (3) UI. Reutilizamos el marco de 5 subcomponentes — **no se reconstruye**.

## 1. Universo verificado (SIB en vivo, 2025-12)

| tipoEntidad | Qué es | Nº entidades | Materialidad |
|---|---|---|---|
| `ARC` | Agentes de Remesas y Cambio | 6 | Alta — CaribeExpress, CibaoExpress, MoneyCorps, GiroSol, RemVimenca, Capla |
| `AC` | Agentes de Cambio | 35 | Baja — mayoría ventanillas pequeñas, balances cercanos a cero |
| `FID`/fiduciarias | Fiduciarias | 0 (no expuesto) | N/D en esta API |

**Recomendación de alcance:** construir el submodelo para las **6 ARC** (tienen
balances reales y son las relevantes para inteligencia de mercado) y las **AC
con activos por encima de un umbral mínimo**. Calificar las 35 AC completas
añade ruido (muchas con estados casi vacíos); se listan pero se marca "sin
rating significativo" bajo umbral.

## 2. Datos disponibles (EIC) vs. el modelo de crédito

Los EIC publican (estructura long-format `conceptoNivel1/2/valor`, igual que EIF):

- **Balance** (`estados/situacion/eic`): Activos (fondos disponibles,
  inversiones, propiedades/muebles/equipos), Pasivos, Patrimonio, Cuentas
  contingentes.
- **Resultados** (`estados/resultados/eic`): ingresos, gastos, impuestos,
  resultado antes/después de impuesto.

**Lo que NO existe para cambiarias** (y por qué el modelo de banca no aplica tal
cual): no hay **cartera de crédito**, ni **morosidad**, ni **solvencia
regulatoria (APR/RWA)**. Por tanto los 19 indicadores de crédito no se trasladan
directo: hay que **reinterpretar los subcomponentes**.

## 3. Metodología propuesta — adaptar el marco de 5 subcomponentes

Perfil de pesos `cambiaria` (ya en `scoring/weights.py`):
**solidez 35% · calidad 20% · eficiencia 20% · liquidez 20% · diversificación 5%.**
Sube liquidez y eficiencia (negocio transaccional, no de balance), baja calidad
(no hay cartera). Indicadores propuestos por subcomponente:

| Subcomp. | Indicador (cambiaria) | Fuente EIC | Doctrina |
|---|---|---|---|
| **Solidez 35%** | Patrimonio / Activos (capitalización) | balance | Colchón ante shocks |
| | Patrimonio vs. capital mínimo regulatorio | balance + norma SIB | Mínimo = piso, no meta |
| | Apalancamiento (Pasivos / Patrimonio) | balance | Penalizar exceso |
| **Calidad 20%** | Calidad de activos: % líquidos vs. fijos | balance | Activos productivos vs. inmovilizados |
| | Exposición a cuentas por cobrar / contingencias | balance | Riesgo de contraparte |
| **Eficiencia 20%** | Cost-to-income | resultados | Eficiencia operativa |
| | Margen operativo (comisiones FX/remesas − gastos) | resultados | Sostenibilidad |
| | ROA / ROE | balance + resultados | Rentabilidad ajustada |
| **Liquidez 20%** | Fondos disponibles / Pasivos exigibles | balance | **Crítico** en casas de cambio |
| | Posición de liquidez inmediata | balance | Capacidad de operar |
| **Diversif. 5%** | Concentración de ingresos (cambio vs. remesas vs. otros) | resultados | HHI de ingresos |

**Overlay cualitativo (fuera de score):** el riesgo dominante de estas entidades
es **AML/cumplimiento**, que no está en los estados financieros. Se propone un
**overlay de outlook** (igual que el IRMP en banca) basado en sanciones/
observaciones de la SIB cuando exista la fuente — no afecta el score intrínseco.

Escala SDQ-AAA…SDQ-D: la misma. Recalibración de umbrales por la naturaleza del
negocio (los rangos de ROA/liquidez difieren de un banco).

## 4. Plan de implementación (por fases, tras aprobación)

1. **Aprobación metodológica** (este documento) + fijar set de indicadores y
   umbrales de cambiaria.
2. **ETL EIC**: en `sib_data_client` añadir parseo de `estados/situacion/eic` y
   `estados/resultados/eic`; en `sib_sync` mapear `AC`/`ARC` → `BankType.cambiaria`
   (hoy `_TIPO_TO_BANKTYPE` no los incluye). Decisión de modelo de datos:
   (a) reutilizar `BankingData` poblando solo los campos aplicables + unos pocos
   campos cambiaria, o (b) modelo `EICData` separado. **Recomendado (a)** para
   reutilizar scoring/UI, con un flag de `entity_type`.
3. **Scoring**: funciones de indicadores de cambiaria + el perfil de pesos (ya
   existe) → reutiliza `engine.run_scoring`. Umbral de materialidad para AC.
4. **UI**: reemplazar "Submodelo en construcción" del dashboard por la vista de
   cambiarias (ranking, ficha por entidad, histórico) reutilizando los componentes
   de banca.

## 5. Fiduciarias — fuente encontrada y metodología (revisado 2026-06-10)

> **Corrección:** la conclusión de 2026-06-08 ("no hay fuente") era incorrecta.
> La API de estadísticas no las expone, pero el **portal de supervisados sí publica
> los estados auditados** en PDF. Investigación rehecha a fondo el 2026-06-10.

### 5.1 Fuente verificada

- **Página por entidad**: `sb.gob.do/supervisados/fiduciarias/<slug>/`. Los enlaces a
  PDF están **server-side en el HTML** → un scraper `requests + regex` los descubre
  (no hace falta navegador headless). Patrón de enlace: `/media/<id>/<nombre>.pdf`.
- **Formato**: estados **auditados anuales** (al 31-dic), un PDF por año, con
  **comparativo del año anterior** en cada PDF. Son escaneos **con capa de texto OCR
  embebida** (Creator `PaperStream Capture`) → `pdftotext -layout` saca balance y
  resultados con líneas y totales. Pequeños artefactos OCR en etiquetas (no en cifras).
- **Estructura contable**: IFRS comercial (Activos circulantes/no circulantes,
  Patrimonio, Comisiones fiduciarias, Gastos operacionales) — **no** el árbol de
  conceptos del SIB. Sin cartera de crédito, sin morosidad, sin solvencia regulatoria.

### 5.2 Universo real (discovery 2026-06-10)

| Fiduciaria | Slug | Estados entidad | Fideicomisos públicos |
|---|---|---|---|
| Fiduciaria Reservas | `fiduciaria-reservas` | 2020–2025 (6) | **20** (solo 2025) |
| Fiduciaria BHD | `fiduciaria-bhd` | 2020–2025 (6) | 0 |
| Fiduciaria Popular | `fiduciaria-popular` | 2020–2025 (6) | 0 |
| Fiduciaria La Nacional | `fiduciaria-la-nacional` | 2020–2025 (6) | 0 |
| FiduAPAP | `fiduapap` | **0 (no publica)** | 0 |

- **Solo Reservas** publica estados de fideicomisos (administra los **públicos/del
  Estado**: FDI, CONFIE, RD VIAL, FONVIVIENDA, MIVIVIENDA, PND, etc. — 20 en 2025).
  Las demás administran fideicomisos privados, que no publican.
- **FiduAPAP** no publica estados en su ficha → se lista pero **N/D** (nunca fabricar);
  retomar si aparece fuente (memoria anual / pedido directo a la SIB).

### 5.3 Metodología — adaptar los 5 subcomponentes (perfil `fiduciaria` ya en `weights.py`)

Pesos: **solidez 35 · calidad 20 · eficiencia 25 · liquidez 10 · diversificación 10**
(eficiencia/diversificación pesan más: negocio de comisiones, no de balance). Indicadores
v1 (calibrables), todos desde los estados auditados:

| Subcomp. | Indicador | Cálculo (campos `BankingData`) |
|---|---|---|
| **Solidez 35** | Capitalización | Patrimonio / Activos |
| | Apalancamiento (inverso) | Pasivos / Patrimonio |
| **Calidad 20** | Calidad de activos | Activos líquidos / Activos |
| | Concentración de cuentas por cobrar | (Clientes + Entes relacionados) / Activos (inverso) |
| **Eficiencia 25** | Cost-to-income | Gastos operacionales / Ingresos (inverso) |
| | ROA / ROE | Utilidad neta / Activos · / Patrimonio |
| **Liquidez 10** | Cobertura líquida | Efectivo / Pasivos circulantes |
| **Diversif. 10** | HHI de ingresos | Comisiones fiduciarias vs otros (HHI, inverso) |

- **Integridad**: indicador sin su input = **N/D** y se repondera (misma regla que banca).
- **Anual**: `period_type = annual`, `period_end = YYYY-12-31`. En la app (período
  trimestral) las fiduciarias aparecen bajo el **Q4** de cada año.
- **Overlay cualitativo (fuera de score)**: exposición a fideicomisos públicos / partes
  relacionadas y riesgo AML — no está en los estados; overlay de outlook si hay fuente.

### 5.4 Fideicomisos públicos — **Índice de Salud del Fideicomiso** (escala propia)

Los fideicomisos públicos (administrados por Reservas) **se califican**, pero con un
índice propio — **no** la escala SDQ-AAA…D de bancos (no se mezclan fondos con bancos).
Razón: son **muy heterogéneos** (verificado 2026-06-10): RD VIAL es una concesión vial
operativa de RD$99.9B apalancada con bonos (patrimonio/activos 12%, peajes 12.8B); FDI es
un fondo tenedor de terrenos de RD$19.9B casi sin pasivos (patrimonio/activos 97%, ingresos
~0). Una escala tipo banco rankearía FDI por encima de RD VIAL por "solvencia" — engañoso.

**Esqueleto común** (presente en todo estado de fideicomiso): Total activos · Total pasivos
· **Patrimonio fideicomitido** (= aportes del fideicomitente + resultado del período) ·
Ingresos operacionales · Gastos operacionales · Resultado del período.

**3 dimensiones universales** (las que generalizan sin engañar; apalancamiento se **excluye**
del score porque en infraestructura es por diseño):

| Dimensión | Indicador | Lectura |
|---|---|---|
| **Solvencia patrimonial** | Patrimonio fideicomitido / Activos | Fondo neto-positivo; patrimonio negativo = bandera roja |
| **Liquidez** | Activos líquidos (efectivo+depósitos+inversiones) / Pasivos circulantes | Capacidad de cumplir obligaciones cercanas |
| **Sostenibilidad** | Resultado del período ≥ 0 (excedente vs déficit) | Déficit persistente erosiona patrimonio |

- **Escala propia** (ej. "Salud: Sólida / Estable / En vigilancia / Frágil"), **no** SDQ-A…D.
- **Segmentado por naturaleza** del fondo (operativo / tenedor / desarrollo) para lectura
  correcta; el apalancamiento se **muestra como contexto**, no puntúa.
- **Periodicidad variable** (RD VIAL es semestral, otros anuales) → se toma el último estado
  publicado por fondo; `period_end` real del PDF.
- Integridad N/D: dimensión sin input se excluye; nunca fabricar.

### 5.5 Plan de implementación (reusa el patrón de cambiarias — no reinventar)

0. **`fiduciaria` ya está**: `BankType.fiduciaria` (enum + migración `b7c1e9a2d3f4`),
   perfil de pesos en `weights.py`, `PeriodType.annual`. No hace falta migración de enum
   para el tipo. **Sí** hace falta agregar `DataSource.sib_pdf` (migración 1 línea,
   patrón conocido `ALTER TYPE … ADD VALUE`) para linaje.
1. **ETL PDF** (`fiduciaria_pdf_client.py`): descubre PDFs por ficha (HTML server-side),
   descarga por entidad/año, `pdftotext -layout`, **parsea** balance + resultados a
   campos de `BankingData`, mapea `(bank_id, period_end=YYYY-12-31, source=sib_pdf)`,
   persiste lo derivado y **descarta el PDF**. Parser por **etiqueta con fallbacks**
   (tolerante a artefactos OCR), cifra exacta; **valida contra Reservas 2024**
   (Activos 2,031,047,582; Ingresos 1,334,368,596). Job en background con **estado/fase
   en DB** (patrón `sib_sync`), errores user-facing en español.
2. **Auto-registro** de las 5 fiduciarias como `Bank(bank_type=fiduciaria)`.
3. **Scoring**: `scoring/fiduciaria.py` (espejo de `cambiaria.py`) + branch
   `entity_type == "fiduciaria"` en `engine.run_scoring`. Reusa `batch.py` para calificar.
4. **Fideicomisos públicos**: modelo ligero de seguimiento + ingesta de los 20 PDF de
   Reservas (activos administrados / flujos), vista de transparencia.
5. **UI**: vista de fiduciarias (ranking + ficha + histórico anual; el frontend ya conoce
   el `entity_type`) + sección "Fideicomisos públicos".
6. **Verificación**: tests de parser (contra cifras conocidas) + scoring; E2E en navegador.

**Riesgo principal**: fragilidad del parseo de PDF (el layout varía por año/auditor) →
mitigado con matching por etiqueta + validación contra cifras conocidas + N/D ante duda.

## 6. Decisiones que requieren tu input

1. **Alcance de cambiarias** (ya implementado): histórico v1 con las 42; calibración de
   umbrales de remesas pendiente (float).
2. **Fiduciarias — fideicomisos públicos**: confirmado **transparencia, no rating**
   (§5.4). Si preferís calificarlos también, decirlo.
3. **Set de indicadores fiduciaria** (§5.3): ¿se aprueba como v1 para arrancar el ETL?
