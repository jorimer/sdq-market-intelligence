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
