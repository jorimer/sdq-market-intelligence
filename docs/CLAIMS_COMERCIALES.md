# Claims comerciales — qué se puede afirmar de cada producto (y qué NO)

**Propósito.** Que el pitch nunca prometa más de lo que el código sostiene. Un comprador
institucional (banco, fondo, gremio) puede auditar; el mayor riesgo reputacional de SDQ·MIP
es una brecha entre marketing y código. Este doc fija el lenguaje permitido por producto.
Deriva de la due-diligence 2026-07-13 (`docs/RUBRIC_AUDIT_AND_REMEDIATION.md`, re-emisión).

**Regla madre.** Distinguir siempre tres cosas en cualquier material de venta o reporte:
1. **Dato medido** — viene de una fuente externa verificable (rotulado `live`).
2. **Juicio experto** — valor de criterio de la casa, declarado, fechado y atribuido (rotulado `rubric`).
3. **Modelo** — o es *entrenado* (aprende de un desenlace externo y tiene backtest honesto) o
   es un *índice explicable* (fórmula transparente). No se dice "predictivo" de un índice.

---

## Reglas duras por producto

### Rating bancario (banking_score) — XGBoost
- ✅ SE PUEDE decir: "scoring de entidad **explicable y auditable**, con evidencia por-eje y
  procedencia por variable"; "aproximador del método SDQ que preserva la explicabilidad".
- ❌ NO se puede decir: "**modelo predictivo** de default/quiebra". El XGBoost aprende a
  reproducir la rúbrica determinista (features → tiers derivados de esos mismos indicadores,
  split aleatorio en `modules/banking_score/ml/xgboost_model.py`). Su F1 alto mide fidelidad a
  la fórmula, **no** poder predictivo sobre un desenlace externo. El foso es la explicabilidad,
  no el ML.

### Política monetaria / TPM (macro_monitor) — XGBoost
- ✅ SE PUEDE decir: "**modelo predictivo** con backtest honesto"; "backtest expanding-window
  one-step-ahead, macro-F1 contra baseline 'siempre hold', panel point-in-time"; "track record
  en vivo (`tpm_forecast_log`)".
- ⚠️ MATIZAR: el track record en vivo **arranca vacío** y crece ~1 registro por reunión de
  política monetaria. Decir "track record **en construcción**", no "track record probado".
  Declarar el leakage residual conocido (usa valores finales, no vintages).

### Deal Scoring
- ✅ SE PUEDE decir: "**índice de atractivo explicable**"; "rúbrica de 7 ejes anclada a IAI/IRMP/IRC
  reales"; "IP metodológica de la casa".
- ❌ NO se puede decir: "**probabilidad** de éxito/default entrenada" ni "modelo predictivo". El
  código es rúbrica declarada, auto-rotulada `is_trained_model: False` (`scoring/rubric.py`). La
  graduación a XGBoost está en cold-start (cosecha de desenlaces en curso).

### IRMP (riesgo macro-político)
- ✅ SE PUEDE decir: "índice de riesgo país sobre **dato real** de gobernanza (WGI), macro (WDI),
  rating soberano y eventos (GDELT), **más juicio experto declarado** en 3 variables
  institucionales".
- ❌ NO se puede decir: "**100% dato**" ni "rúbrica cero". Tres inputs (`policy_continuity`,
  `discretion`, `contract_enforcement`) son juicio experto de `regulatory.yaml` (~0.30 del peso),
  rotulados. Es legítimo y estándar en rating; presentarlo como medición no lo es.

### Índices sectoriales (IAI/SGPS) e IRC, seguros, pensiones, ESG, social
- ✅ SE PUEDE decir: "compuesto de **dato real** con **procedencia por variable** (badge live/rubric)";
  "las dimensiones sin dato se **declaran brecha y se excluyen**, no se rellenan".
- ⚠️ MATIZAR donde aplique: `ease_of_business` del IAI es rúbrica fija (Doing Business se
  discontinuó, sin fuente viva); ciertos períodos usan fallback neutral rotulado. La UI ya lo
  muestra; el material de venta debe ser consistente con ese rótulo.

---

## Cómo se sostiene esto en el producto

- **Badge de procedencia** `sources: {var: "live"|"rubric"}` en cada `assemble_*_dataset` → visible
  en UI y declarado en la narrativa. Es la evidencia de que el rótulo no es cosmético.
- **Guardrail numérico** (`shared/narrative/numeric_guard.py`): recomputa cifras antes de publicar.
- **Gate de readiness**: un producto no se publica bajo el umbral de su nivel.

**Si un comprador pregunta "¿esto es dato o criterio?"** la respuesta correcta siempre existe a
nivel de variable y está rotulada. Ese es el argumento de venta —transparencia auditable—, no una
debilidad a esconder.

---

## Credenciales de validación — qué cifra se puede citar, y de dónde sale

**Añadido 2026-08-19** (Fase 6 del [plan de cierre](PLAN_CIERRE_BRECHAS_VALIDACION.md)).

**La fuente es una sola y se computa:** `GET /api/v1/products/credenciales`
([`shared/products/credenciales.py`](../shared/products/credenciales.py)). Lee el reporte
persistido de cada motor y arma la afirmación con sus cifras. **Ninguna cifra de validación se
escribe a mano en material comercial.** Si hace falta un número para un deck, sale de ahí.

### El gate

Cada credencial trae `publicable`, y solo es `True` cuando la cifra existe **y** su reporte se
verificó vigente contra el insumo que lo produjo. Es asimétrico a propósito:

| Frescura | ¿Publica? |
|---|---|
| `stale: false` — verificada vigente | **sí** |
| `stale: true` — el insumo cambió después del cálculo | no |
| `stale: null` — **indeterminado** | **no** |

El tercer caso es el que importa. «No sé de cuándo es» y «está al día» son cosas distintas:
producción sirvió 19 días un Gini de 0,44 calculado con un score que ya no existía, mientras
el deck decía 0,16. Las cifras vetadas se listan en `vetadas_por_frescura` en vez de
desaparecer — un veto silencioso se lee como que el eje no tiene validación.

### Los seis grupos, y por qué no se mezclan

«Tiene validación» abarca cosas que no sostienen el mismo argumento de venta:

| Grupo | Qué autoriza a decir |
|---|---|
| **A · evento real** | discriminación contra desenlaces reales de entidades |
| **B · concluyente** | discriminación contra un desenlace realizado, con IC que no cruza cero |
| **C · convergente** | coincide con una medida independiente del mismo período — **no** es backtest temporal y no se vende como tal |
| **D · parcial** | metodología exigente con resultado acotado, declarado |
| **E · corrido y no concluyente** | el Gate E se aplicó y **dio negativo**. Honesto; no es credencial |
| **F · sin backtest** | descriptivo, con el obstáculo declarado (ver `docs/TRIAJE_VALIDACION_EJES.md`) |

### Banca: las tres correcciones que el material tenía mal

1. **Son TRES cohortes evaluables, no seis.** Los seis bancos están en el ledger, pero el
   onset exige una regla de crédito y la morosidad no existe antes de 1993-12: tres no pueden
   disparar por construcción. Citable: **3 evaluables, 2 detectados con anticipación
   (Bancrédito 11 meses, Baninter 7) y 1 señal tardía (Mercantil)**. Decir «seis» infla el
   denominador sin agregar evidencia.
2. **El Gini NO es validación contra quiebras.** El desenlace del backtest es *distress
   financiero*, y medido en producción es **83 % pérdidas sostenidas, 22 % deterioro de
   crédito y 0 % solvencia** — esta última regla nunca disparó. Contra la regla de crédito el
   score discrimina **invertido**. Citar el agregado sin decir de qué está hecho es la
   afirmación más frágil del catálogo.
3. **La credencial fuerte de banca es la cohorte, no la curva por banda.** La tabla de
   distress por banda **no ordena el riesgo** (la banda «Sólida», con el N más grande, tiene
   más deterioro que las dos siguientes) y ninguna superficie la presenta como ordenamiento.
   No entra a material comercial.

### Qué número de banca se cita

La tabla de credenciales lidera con la **señal**, no con el agregado, y hay que citarla así:

- ✅ **Gini 0,2287 · IC [0,147 · 0,311] · n=1.693 · 250 eventos, señal «resultados»** — la
  discriminación contra pérdidas sostenidas, que es la señal concluyente del eje.
- ⚠️ El **agregado 0,1615** sigue siendo correcto y es el que citó el deck, pero **solo se
  puede usar diciendo de qué está hecho** (83 % resultados · 22 % crédito · 0 % solvencia).
  Solo, se lee como discriminación de riesgo de crédito, que es donde el score falla.
- ❌ **Nunca** «Gini 0,16 contra quiebras». El desenlace es distress, no quiebra.

### Y el catálogo son 16 ejes

Fuente canónica: `shared/products/registry.py::PRODUCT_CATALOG`. El «14» era correcto el
13-jul-2026 (Catálogo v3); entraron `social_dev` (09-ago) y `law` (15-ago). Dimensionar sobre
14 subdeclara el catálogo en dos.
