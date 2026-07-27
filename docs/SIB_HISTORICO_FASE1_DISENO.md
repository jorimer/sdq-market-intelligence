# SIB Histórico 1947–2026 · Diseño Fase 1 (crosswalk + modelo de datos)

> Estado: **diseño para aprobación**. No se ha escrito ETL todavía.
> Fuente: microportal *Cronología SB* → 7 CSV crudos públicos (`sb.gob.do/media/...`),
> snapshot 19-jul-2026. Balance 1947-10→2026-04, Resultados 1996-01→2026-04.
> ~2.79M filas, por entidad, mensual. Ver memoria `sib-historico-1947-csv`.

## 1. Objetivo

Incorporar el libro mayor histórico del sistema financiero RD como **fuente de
profundidad histórica** para: (a) backtest del motor *Alerta Temprana* contra los
bancos que realmente quebraron; (b) percentiles y baselines multi-década en los
Deep Dives. **Complementa** la API v2 en vivo (no la reemplaza).

## 2. Modelo de datos (2 tablas — separación cruda/derivada)

Decisión de diseño (excelencia sobre atajo): NO volcar directo a `banking_data`.
El CSV es formato largo (1 fila = entidad×período×línea); `banking_data` es ancho
(1 fila = banco×período). Se aíslan en dos capas:

**2.1 `sib_historical_ledger`** (landing crudo, auditable, re-derivable)
```
id (uuid)  ·  estado {situacion|resultados}  ·  fecha (date)  ·  ano  ·  mes
periodicidad  ·  entidad_code  ·  entidad_nombre  ·  tipo_entidad  ·  sector
tipo_capital  ·  nivel_1  ·  nivel_2  ·  nivel_3  ·  nivel_4  ·  monto (numeric)
monto_desagregado (numeric, solo resultados)  ·  snapshot_date  ·  source_file
UNIQUE(estado, fecha, entidad_code, nivel_1, nivel_2, nivel_3, nivel_4)
```
Preserva el dato tal cual. ~2.8M filas → trivial en Postgres.

**2.2 Derivación → `banking_data`** (para el motor de scoring)
Un paso de pivote agrega el ledger a las columnas de `banking_data` (ver crosswalk
§3) con `source = DataSource.sib_historical` (enum NUEVO) y `period_type = monthly`.
Solo se derivan las entidades/períodos que vayamos a puntuar o backtestear.

> Nuevo valor de enum: `DataSource.sib_historical`. Migración Alembic añade la tabla
> + el valor de enum. Cuidar parity SQLite(dev)/Postgres(prod) (enum nativo PG).

## 3. Crosswalk línea-histórica → inputs de indicadores

Validado con Banco Popular Dominicano, dic-2023 (activos RD$755.3B, utilidad
RD$22.9B, NPL≈0.63%, cobertura≈472% — todo en rango real).

### 3.1 Balance (`estado = situacion`)

| Campo `banking_data` | Regla de extracción (filtro sobre el ledger) |
|---|---|
| `activos_totales` | NIVEL_1=`Activos` ∧ NIVEL_2=`Total` |
| `cartera_bruta` | Σ NIVEL_2=`Cartera de créditos`, NIVEL_3 ∈ {Vigentes, Reestructurada, Vencida(+90d), En mora(31-90), Cobranza judicial, Rendimientos por cobrar} (excluye `Provisiones para créditos`) |
| `cartera_neta` | `cartera_bruta` + (Provisiones para créditos, que viene negativa) |
| `provisiones` | NIVEL_3=`Provisiones para créditos` (valor absoluto) |
| `cartera_vencida_90d` | Σ NIVEL_3 ∈ {`Vencida (más de 90 días)`, `Cobranza judicial`} |
| `depositos_totales` | NIVEL_2=`Depósitos del público` |
| `activos_liquidos` / `caja_valores` | Σ NIVEL_2 ∈ {Efectivo y equivalentes, Inversiones, Fondos interbancarios} |
| `patrimonio` (patrimonio_promedio base) | NIVEL_1=`Patrimonio` ∧ NIVEL_2=`Total` |
| `pasivos_cp` / `pasivos_exigibles` | NIVEL_1=`Pasivos` ∧ NIVEL_2=`Total` (proxy; refinar con NIVEL_2 exigibles) |

Morosidad (%) = `cartera_vencida_90d / cartera_bruta`; cobertura =
`provisiones / cartera_vencida_90d`. Ambos derivables desde 1947.

### 3.2 Resultados (`estado = resultados`, esquema NIVEL_1..2 + `MONTO_DESAGREGADO`)

| Campo `banking_data` | Regla (NIVEL_1) |
|---|---|
| `utilidad_neta` | `Resultado del ejercicio` |
| `ingresos_financieros` | `Ingresos financieros` |
| `gastos_financieros` | `Gastos financieros` |
| `ingresos_operacionales` | `Resultado operacional bruto` (o Σ ingresos) |
| `gastos_operacionales` | `Gastos operativos` |
| margen (`margen_pct` base) | `Margen financiero bruto` / `Margen financiero neto` |
| provisiones P&L | `Provisiones` |

ROA = utilidad_neta / activos_promedio; ROE = utilidad_neta / patrimonio_promedio;
eficiencia = gastos_operativos / ingresos. Derivables desde 1996.

## 4. Limitaciones honestas (documentar, no enmascarar)

1. **Capital regulatorio ausente en deep-history.** `patrimonio_tecnico`, `apr`,
   `capital_tier1`, `solvencia_pct` (Basilea) son regulatorios (~post-2004 en RD),
   NO están en el balance contable. Para 1947–2003 se usa **proxy de apalancamiento**
   (`patrimonio/activos`) y se marca explícitamente como proxy. La solvencia Basel
   real sigue viniendo de la API v2 para el período moderno.
2. **P&L acumulado YTD.** El monto de resultados a dic = año completo (verificado:
   BPD ingresos 2023 = 129.8B). La cadencia mensual parece ser acumulada dentro del
   año calendario (reset en enero). El ETL debe des-acumular si se quiere flujo
   mensual puro, o usar solo cierres (dic) para ratios anuales. **A confirmar en Fase 2.**
3. **Periodicidad mixta temprana.** Antes de que lo mensual fuera estándar hay
   Anual/Semestral/Trimestral. Preferir mensual donde exista; si no, el período disponible.
4. **Casing/acentos** inconsistentes en `TIPO_ENTIDAD` (2017+) → normalizar con el
   `_norm` existente. Matching de entidad debe reusar el matcher del `sib_data_client`
   (ojo con el guard substring APAP→Popular, Bonao→Bonanza ya conocidos).
5. **Snapshot, no live.** Se re-descarga periódicamente; no sustituye el feed API v2.

## 5. Reconciliación del solape 2012–2026

Antes de confiar en el histórico para períodos que ya tenemos: por cada banco×trimestre
en el solape, comparar `activos_totales`, `depositos_totales`, `utilidad_neta`
derivados del ledger vs los ya cargados por `sib_api`. Misma fuente (SB) ⇒ deben
cuadrar dentro de tolerancia. Regla: **la API v2 manda** para el período moderno;
el histórico manda para pre-2012. Reporte de discrepancias como gate.

## 6. Ejecución propuesta (Fase 2, por PRs)

1. **PR-A** migración: tabla `sib_historical_ledger` + enum `sib_historical`.
2. **PR-B** conector `shared/data/sib_historical_client.py`: descarga los 7 CSV
   (URLs fijas), parsea los dos esquemas, carga idempotente al ledger.
3. **PR-C** derivación ledger→`banking_data` (crosswalk §3) + reconciliación §5.
4. **PR-D (Fase 3)** backtest *Alerta Temprana* sobre cohorte de quiebras +
   percentiles multi-década en Deep Dives.

## 7. Decisiones del dueño (con recomendación)

- **Alcance de carga:** todo el sistema (~180 entidades: múltiples, AAyP, ahorro y
  crédito, corporaciones, públicas) vs solo bancos. → **Recomiendo: todo** (barato;
  habilita la vista sistémica del early-warning).
- **Ratings históricos:** derivar inputs + backtest, pero **NO publicar ratings
  históricos como producto** (no implicar que "calificamos" bancos en 1970). →
  **Recomiendo: histórico = motor de backtest/contexto, no SKU publicado.**

## Anexo · Cohorte de quiebras (backtest)

2003: Baninter (1986–2003), **Bancrédito = "Banco Nacional de Crédito"** (1981–2003),
Banco Mercantil (1985–2005), Banco Global (1996–2002). Otros: Banco Peravia
(1994–2014, fraude), Banco Osaka (1995–2001), Banco Dominicano del Progreso
(1984–2020), Republic Bank (2005–2007) + decenas de entidades menores salidas.
