# DIAGNÓSTICO Y PLAN DE HARDENING — Eje 2 `macro_monitor`

**Fecha:** 2026-06-15 · **Estado:** propuesta para decisión del dueño (no rector) · **Autor:** asesoría técnica
**Relación con plan maestro:** subordinado a `docs/PLAN_MAESTRO_DESARROLLO.md`. No reordena fuentes; propone cerrar Eje 2 a profundidad antes de declararlo hecho.

---

## 0. BLUF (la respuesta incómoda primero)

El problema de Macro **no es que la información sea débil**. Tenés 292 series con histórico completo backfilled y, desde T3, capa de IA. El problema es que **el módulo aún no pasó Gate D con honestidad**: lidera con su peor cara (un muro de "Insuficiente"), tiene un bug de fecha que mata credibilidad, y nunca cruza de *indicador* a *implicación* — que es exactamente lo que tu propio framework de niveles (PDF) y el template sectorial exigen.

Lo barato resuelve la percepción de debilidad (puntos 1–3, esfuerzo bajo, causa raíz confirmada en código). Lo valioso evita que esa debilidad se propague a los sectoriales (puntos 4–5). **Ninguno requiere reordenar el plan maestro.** Tres de los cinco son "terminar lo que Gate C/D ya pedía", no alcance nuevo.

---

## 1. Causa raíz confirmada (leído en código, no inferido)

| # | Síntoma visible | Causa raíz | Evidencia |
|---|-----------------|-----------|-----------|
| A | ~80% de la tabla de momentum dice **"Insuficiente"** | `compute_series_momentum` devuelve `trend="insuficiente"` cuando `len(clean) < 2`. El `service` alimenta solo el período seleccionado (Q1) → 1 punto por serie en la mayoría. La data histórica **está en la DB**; no se le pasa al cálculo. | `modules/macro_monitor/scoring/momentum.py` L59-61; backfill confirmado en plan §1. |
| B | Resumen IA fechado **"Diciembre 2026"** (futuro) con filtro en Q1 | Data de períodos futuros filtrándose al snapshot. Remedio ya existe, falta en UI. | `POST /data/prune-future` (listado en `tasks/todo.md` T2). |
| C | "292 series / 2 señales activas" se lee como impotencia del motor | Decisión de diseño: la tabla cruda de 292 es el elemento protagonista; la narrativa SCQA (lo bueno) está debajo. | Screenshots; `pages/MacroMonitorPage.tsx`. |
| D | El módulo nunca dice "y esto qué significa para quién" | No existe capa de traducción indicador→agente. No está en el código ni en el plan. | Ausente en `ai_context.py` / template; presente como requisito en PDF de niveles + template sectorial §2 y §8. |

**Implicación:** A y B son fixes de wiring/datos de **esfuerzo bajo y alto retorno de credibilidad**. No son "data débil". Tratarlos como tal sería el anti-patrón §0.2 (falsa imposibilidad / N/D prematuro) al revés: subestimar lo que ya está en mano.

---

## 2. Corrección de premisa (para fijar la secuencia)

- **T4 ≠ sectoriales.** T4 = *Backtest MVP del Eje 1* (banking_score). Sectoriales = **Eje 3 (ONE)**, prioridad 2, detrás de WGI (Eje 4, prioridad 1). Están **dos fuentes después**.
- **Lo que acabás de cerrar es T3** (retrofit IA en macro). Por eso ves la "Lectura de coyuntura". Macro está hoy en **Gate D recién puesto, Gate E (backtest) pendiente**.
- **Consecuencia:** no hay urgencia de construir el puente macro→sectorial esta semana. Sí hay urgencia de cerrar 1–3, porque son la cara débil del producto y son baratos.

---

## 3. Los cinco puntos — gate, esfuerzo, dependencia

> Esfuerzo en la escala del plan (§3: bajo/medio/alto), **ganado por lectura de código**, no por reloj. No se importa calibración humana (§0.3).

| # | Acción | Gate | Causa raíz que cierra | Esfuerzo | Depende de | Blast radius |
|---|--------|------|----------------------|----------|-----------|--------------|
| **1** | **Fix de fecha futura.** Subir `prune-future` a UI (o correrlo) + asegurar que el snapshot del período no incluya futuros. | A/F (integridad + operabilidad) | B | **Bajo** | Endpoint ya existe; UI = parte de T2 | Snapshot macro + resumen IA |
| **2** | **Arreglar la ventana de momentum.** Alimentar a `compute_series_momentum` la serie histórica completa (no solo el período), para que `trend` y `acceleration` se computen sobre ≥3 puntos donde existan. Curar la tabla a ~25–30 series cabecera; separar/colapsar las que de verdad tienen <2 obs. | C | A | **Bajo–Medio** | — | `service.py` (query) + tabla en `MacroMonitorPage.tsx` |
| **3** | **Cambiar el héroe.** Subir la "Lectura de coyuntura (IA)" (SCQA) a primer plano; degradar la tabla de 292 a drill-down/anexo. Cabecera deja de gritar "2 de 292". | D (presentación) | C | **Bajo–Medio** | 2 (idealmente) | `MacroMonitorPage.tsx` (layout) |
| **4** | **Capa de traducción.** Por cada señal activa / clúster acelerando, una línea "qué significa para empleado / PyME / gran empresa", usando el framework del PDF. Extiende el template de IA (`executive_summary` → + bloque de implicaciones por agente). | D (alcance nuevo) | D | **Medio** | 3 | `ai_context.py` + template + render |
| **5** | **Contrato macro→sectorial.** Objeto estructurado por período: 5–8 factores macro con dirección + magnitud + a qué sectores/agentes golpea. Vive en `shared/` y alimenta la §2 del informe sectorial. | Arquitectura (anti-Frankenstein) | D | **Medio** | 4 + inicio de Eje 3 | `shared/`; consumido por Eje 3 |

---

## 4. Secuencia recomendada (y por qué, respetando el plan maestro)

**Disiento de tratar Macro como "sección terminada".** Mi alternativa: reconocer que **1–3 son deuda de Gate C/D, no alcance nuevo** — la §0.1 dice que una página sin terminar no se cierra, y un muro de "Insuficiente" + fecha futura es justamente eso. Hacerlos ahora **no rompe la doctrina "una tarea a la vez"**: son el cierre real de Eje 2.

```
AHORA (cierre honesto de Eje 2, antes/junto a T4):
  Punto 1  → fix de fecha          [bajo]      ← credibilidad, minutos
  Punto 2  → ventana de momentum   [bajo-medio]← mata el muro "Insuficiente"
  Punto 3  → reordenar el héroe    [bajo-medio]← deja de verse débil
        └─ con esto, Eje 2 pasa Gate D de verdad.

LUEGO (diferenciación analítica, decisión explícita de alcance):
  Punto 4  → capa de traducción    [medio]     ← el "so what" por agente

CUANDO ARRANQUE EJE 3 / ONE (no antes):
  Punto 5  → contrato macro→sectorial [medio]  ← construir productor y
            consumidor juntos; no especular una interfaz 2 fuentes antes
            de que exista su consumidor (impacto mínimo).
```

**Por qué 5 no se hace ahora:** construir el contrato hoy es diseñar una abstracción sin su consumidor (Eje 3 está a dos fuentes). Riesgo concreto: se hard-codea el shape equivocado y se reescribe al llegar ONE. La decisión correcta hoy es **documentar el contrato como requisito de diseño** y construirlo al abrir Eje 3 — no codificarlo en especulación.

**Por qué 4 va después de 1–3 y no antes:** la traducción por agente luce mal sobre una tabla rota y una fecha futura. Primero la base creíble, luego el diferenciador.

---

## 5. Lo que NO recomiendo

- **No** "cargar más series" para que la tabla se vea llena. El problema es profundidad de ventana, no amplitud. Más series empeora el ruido.
- **No** reordenar fuentes para meter sectoriales antes que WGI. El plan §3 lo confirma con el dueño; el único disparador legítimo sería un pipeline comercial concreto que exija sectorial ya (§3 nota).
- **No** construir el puente macro→sectorial esta semana (punto 5). Documentarlo, sí; codificarlo, no.

---

## 6. Decisiones registradas (dueño, 2026-06-15)

1. **Puntos 1–3 (hardening de macro):** se ejecutan **al terminar T4** (T4 está casi listo). Quedan como **T4B** en `tasks/todo.md`, corriendo tras T4 y antes de T5 (WGI) — cierra Eje 2 a profundidad antes de abrir Eje 4.
2. **Punto 4 (capa de traducción):** **diferido al sprint de diferenciación.** Registrado en la deuda de `tasks/todo.md`.
3. **Punto 5 (contrato macro→sectorial):** **documentado hoy** (este doc, §3–4), se **construye al abrir Eje 3 (ONE)**, no antes. Registrado como **requisito de diseño de Eje 3** en la deuda de `tasks/todo.md`: la §2 del informe sectorial consume el contrato, no re-deriva macro a mano.

> Cada punto entra al ciclo del plan maestro: plan fino en `tasks/todo.md` → confirmación del dueño → implementación → sensor → cierre. T4B aún **no se implementa** (T4 en curso); este registro fija la secuencia, no abre código.
