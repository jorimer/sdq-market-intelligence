# Tarea — Corregir la inferencia del Gate E sectorial (IC apilado → IC-mean con t por años)

> **Para:** Claude Code. **Tipo:** corrección de correctitud sobre un número ya en prod.
> **Origen:** revisión de `modules/sector_intel/validation/report.py` (2026-06-19).
> **Proceso:** Plan First (confirmá el plan antes de codear), Verify Done con Sensors,
> Reviewer Subagent antes de cerrar, `tasks/lessons.md` si hay corrección.
> **Sin migraciones.** Cambios en `report.py`, `shared/validation/metrics.py`, tests, y
> el copy del badge en el tab "Validación".

## Contexto / causa raíz

El estadístico de cabecera del Gate E (`gate_e_report`, línea 57) es
`spearman_bootstrap_ci(iai, out)` sobre los **~60 pares sector-año apilados**, y el
bootstrap remuestrea pares individuales (`shared/validation/metrics.py:117`) como si
fueran independientes. No lo son: se agrupan por **año** (shock macro común) y por
**sector** (efecto persistente). Resultado: el CI [-0.24, 0.32] está calculado como si
hubiera 60 observaciones independientes, sobrestimando la precisión.

El estadístico defendible para un panel sector-año es el **IC clásico**: el ρ de
Spearman dentro de cada cross-section anual (ya se calcula en `per_year`, líneas 59-67),
promediado, con inferencia (t) sobre la **serie de ~6-7 ICs anuales** — no un Spearman
sobre 60 pares apilados. Los ingredientes ya existen; falta agregarlos y hacerlos el
titular.

Dirección del error: el bootstrap por pares **subestima** el CI frente a uno por
bloques-año. Corregido, el resultado es *aún más* claramente inconcluso. El veredicto
honesto no cambia de signo — solo deja de sobre-afirmar precisión.

Nota de contexto (no es bug, documentar): el test corre a **10 ramas ENCFT**, no a los
17 sectores (`n_branches` usa `r["branch"]`; el IAI se agrega hacia abajo). Manufactura
local / zonas francas / minería siguen colapsadas en "Industrias" del lado del outcome.
Es una limitación de resolución a dejar explícita en el disclaimer, no a resolver aquí.

## Cambios

### 1. `shared/validation/metrics.py` — helper de inferencia sobre la serie de ICs
Agregar función pura, unit-testable (sin DB):
```python
def mean_ic_with_t(yearly_ics: List[float], alpha: float = 0.05) -> Optional[Dict]:
    """Mean information coefficient + t-test sobre la serie de ICs anuales.
    Devuelve {mean_ic, n_years, sd, t_stat, ci_lo, ci_hi} o None si <2 años.
    Inferencia con t de Student df=n_years-1 (NO normal): n chico es el punto.
    """
```
- `t_stat = mean / (sd / sqrt(k))`, `ci = mean ± t_{0.975,k-1}·sd/sqrt(k)`.
- Implementar el cuantil t sin dependencia nueva si `scipy` no está; si `scipy.stats`
  ya está en requirements, usar `scipy.stats.t.ppf` (preferir lo ya presente —
  impacto mínimo). Verificar antes de añadir dependencias.
- Manejar k<2 → None; sd=0 → t indefinido, devolver `t_stat=None` con disclosure.

### 2. `modules/sector_intel/validation/report.py` — IC-mean como titular
- Tras construir `per_year`, filtrar los años con ρ no-None y pasar esa lista a
  `mean_ic_with_t`. Exponer en el dict de salida: `mean_yearly_ic`, `n_years`,
  `ic_t_stat`, `ic_ci` (la nueva inferencia), y marcarla como el resultado principal.
- **Degradar** el ρ apilado actual a secundario: renombrar la clave a
  `spearman_pooled` con etiqueta/nota `"pooled (sin clustering — sobrestima la precisión)"`.
  Mantenerlo visible por transparencia, pero NO como titular.
- `_quintile_spread`: calcular el spread **dentro de cada año** y promediar (hoy ordena
  los 60 juntos, mezcla efectos-año). Mismo sesgo de clustering, menor magnitud.
- Mantener intacto el parcial controlando `sector_growth_T` (ya correcto).
- Actualizar el `disclaimer`: titular = IC-mean con t sobre n años; mencionar que el
  pooled se reporta como secundario y por qué; dejar explícito que la resolución es 10
  ramas (no 17).

### 3. Frontend — tab "Validación"
- Cambiar el copy del badge de "No significativo" → **"Inconclusivo por potencia (n insuficiente)"**.
- Mostrar el titular nuevo: `mean_yearly_ic`, `n_years`, `ic_ci`, y el mínimo detectable
  como contexto ("con n por año ≈10, el IC mínimo detectable es alto; validación
  direccional, no confirmatoria"). String en español.

## Sensores (correr y reportar output antes de cerrar)
```bash
ruff check shared/validation modules/sector_intel/validation
pytest shared/validation/tests/ modules/sector_intel/tests/test_validation.py -v
pytest --cov=shared/validation --cov=modules/sector_intel/validation --cov-report=term-missing \
       shared/validation modules/sector_intel/validation   # ≥80%
```

## Tests obligatorios
- `mean_ic_with_t`: panel sintético con ICs anuales conocidos → mean/t/CI esperados;
  k<2 → None; sd=0 → t_stat None sin crashear.
- `test_validation.py`: el reporte expone `mean_yearly_ic` como titular y `spearman_pooled`
  como secundario; con una señal fuerte sembrada el IC-mean la detecta; con ruido el CI
  cruza cero y se reporta tal cual (no se maquilla).
- Verificación E2E en prod: el tab "Validación" muestra el titular nuevo y el badge
  "Inconclusivo por potencia" (no "No significativo").

## Definition of Done
- El número de cabecera del Gate E es el IC-mean con t sobre años; el pooled queda
  secundario y etiquetado.
- CI honesto (más ancho que el apilado); badge corregido en prod.
- Sensores en verde, cobertura ≥80% en lo tocado, reviewer subagent sin críticos.
- `tasks/lessons.md` con la entrada: síntoma (CI apilado sobre panel clustered),
  causa raíz (bootstrap de pares independientes ignora year/sector clustering), regla
  (para paneles, inferencia sobre la serie de cross-sections, no sobre pares apilados),
  disparador (cualquier backtest panel sector/entidad × período).

## NO hacer en esta tarea
- No tocar el plumbing de ingesta ni las migraciones.
- No intentar subir la señal (IED, T+2, llenar rúbricas) — son tareas aparte en `todo.md`.
- No cambiar la resolución de 10 ramas; solo documentarla.
