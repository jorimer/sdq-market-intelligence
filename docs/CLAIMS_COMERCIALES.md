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
| **E · corrida y sin credencial a favor** | el Gate E se aplicó y **no dejó una afirmación vendible**. Cubre dos cosas distintas que comparten esa consecuencia: que el intervalo cruce cero (no concluyente) y que **no lo cruce pero esté del lado equivocado** (la señal ordena INVERTIDO, que es un hallazgo, no una ausencia). Honesto; no es credencial |
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

- ✅ La **señal «resultados»** —discriminación contra pérdidas sostenidas, la concluyente del
  eje— **con su población al lado**. Las cifras se leen de
  `GET /api/v1/products/credenciales`, que ahora devuelve `poblacion` junto a cada credencial;
  **no se copian de acá**, porque una cuota escrita a mano se desincroniza en la primera
  recalibración.
- ⚠️ **Y hay que decir sobre QUIÉN se midió.** El panel no es «bancos»: es todo el universo
  supervisado por la SIB, y casi la mitad de las observaciones son entidades de intermediación
  cambiaria y fiduciarias, que **no otorgan crédito** y aportan una parte aún mayor de los
  eventos. Están por diseño del producto (`banking_score/SPEC.md` §1 lo define como un
  *Financial Entity Score*), pero un «Gini · n» solo se lee como discriminación **entre
  bancos**, que no es lo que se midió. El reporte lo declara en un caveat computado y la
  credencial lo lleva en `poblacion.sin_libro_de_credito`.
- ⚠️ El **agregado 0,1615** sigue siendo correcto y es el que citó el deck, pero **solo se
  puede usar diciendo de qué está hecho** (83 % resultados · 22 % crédito · 0 % solvencia).
  Solo, se lee como discriminación de riesgo de crédito, que es donde el score falla.
- ❌ **Nunca** «Gini 0,16 contra quiebras». El desenlace es distress, no quiebra.

### Y el catálogo son 16 ejes

Fuente canónica: `shared/products/registry.py::PRODUCT_CATALOG`. El «14» era correcto el
13-jul-2026 (Catálogo v3); entraron `social_dev` (09-ago) y `law` (15-ago). Dimensionar sobre
14 subdeclara el catálogo en dos.

---

## Licencias de fuente — lo que restringe qué se puede vender

**Regla.** La licencia de una fuente es una condición de venta, no una nota al pie. Y no se
lee de este documento: la declaración canónica de cada fuente vive en su conector y su
verificación en **`shared/data/licenses.py`** (`LICENCIAS`, con `terminos_url` y
`verificado_el`). Una licencia copiada a un doc es una licencia que se desincroniza — que es
exactamente cómo empezó lo de abajo.

**Lo que hay que saber para vender, al 2026-08-23:**

- ⚠️ **UIP / Parline — CC BY-NC-SA 4.0** (Atribución + NoComercial + CompartirIgual). Alimenta
  el indicador **2.43** de la END (mujeres en el Senado) en el eje `law`. El conector decía
  «uso público con cita»: describía la licencia sin sus dos cláusulas restrictivas. La
  atribución ya es obligatoria y **la computa la plataforma** —
  `atribuciones_obligatorias_por_indicador` en el contexto del informe. **`NC` y `SA` siguen
  abiertos**: lo que se publica es una cifra por año leída de la tabla pública, no la base de
  Parline, pero los informes de este eje se venden. **La pregunta ya está hecha al emisor** —
  correo a `postbox@ipu.org` del 2026-08-23, punto 3, sin respuesta todavía. Hasta que
  conteste, no comprometer el 2.43 en material de venta nuevo sin decidirlo caso por caso.
- ⚠️ **EM-DAT / CRED (UCLouvain)** — uso **no comercial**; el comercial exige acuerdo aparte y
  cuota anual con CRED, y prohíbe construir bases sustitutas o derivadas. Llega vía OWID, cuya
  CC-BY cubre **su procesamiento**, no el dato de abajo. Hoy solo alimenta el backtest interno
  del IRC, que no se redistribuye — si ese insumo pasa a material de venta, hay que resolverlo
  antes.
- ✅ **CEPALSTAT — resuelto por el PRODUCTOR, no por sus términos.** Los términos de la CEPAL
  son estrechos —uso personal, no comercial, sin reventa ni obra derivada— y siguen siéndolo.
  Pero gobiernan **su compilación**, no los hechos que compila: los indicadores **2.45 y 2.46**
  los produce la **JCE**, y una cifra electoral oficial dominicana es información pública cuyo
  régimen fija el marco nacional, no el portal que la reexpone. **Se publican, atribuyendo a la
  JCE como productora y a la CEPAL como vía** — la atribución la computa la plataforma.
  Lo que sigue fuera de alcance: reexportar la compilación de la CEPAL como tal.
- ⚠️ **UN Comtrade — no es dato libre.** Es propiedad intelectual de Naciones Unidas, cedida
  para **uso interno**; re-diseminar el dato **original** exige permiso escrito de la UNSD, y
  por encima de 100.000 registros una «license to distribute» paga sobre suscripción premium.
  **El dato transformado no lo alcanza** y ahí está la vía legítima: lo que `trade_intel`
  publica son cálculos propios, no la tabla de Comtrade. La regla práctica para material de
  venta: **cifras derivadas sí, tablas de socio × capítulo tal cual no.**
- ✅ **Banco Mundial (WDI/WGI) — CC-BY 4.0, confirmado.** Se puede redistribuir citando. Con
  un matiz: CC-BY es el **default** del catálogo, no una garantía; hay datasets con ODbL,
  microdatos y términos de terceros. Vale para lo que hoy se lee, no para cualquier serie del
  Banco Mundial que se agregue mañana.
- ✅ **UIT / ITU DataHub — permiso comercial POR ESCRITO.** La plataforma publica
  CC BY-NC-SA 3.0 IGO, pero la División de Datos y Analítica de las TIC autorizó el
  2026-08-18, por correo, el uso de los datos del DataHub «como insumo para productos
  analíticos comerciales, siempre que la UIT sea citada adecuadamente como fuente», y avisó
  que está actualizando sus términos porque **la licencia publicada aún no refleja ese
  cambio**. Es el único caso del catálogo donde lo declarado era MÁS restrictivo que lo
  permitido. **Dos límites que no se pueden soltar:** el permiso cubre el uso como insumo de
  un índice, **no** redistribuir las series en bruto (la consulta lo dijo así y sobre eso se
  concedió); y **citar a la UIT es condición del permiso**, no cortesía editorial. Un informe
  del eje telecom que use estos datos sin nombrar a la UIT incumple — desde el 2026-08-23 la
  atribución **la computa la plataforma** y entra sola en el contexto del informe.
  **Dos puntos de alcance preguntados a la UIT el 2026-08-23 y aún sin respuesta**, que no se
  pueden dar por concedidos mientras tanto: si mostrar cifras individuales de la UIT dentro de
  un informe queda cubierto, y si el permiso alcanza a los informes ya entregados. No son una
  negativa: es alcance sin confirmar. Estado vigente en `shared.data.licenses`.
- ✅ **datos.gob.do — ODbL, y el share-alike NO nos alcanza.** Los datasets del portal se
  publican bajo **Open Database License v1.0**, verificado dataset por dataset contra su CKAN:
  zonas francas (CNZFE), generación y llegadas aéreas (ONE), licencias de construcción
  (MIVHED), potencia instalada y PROTECOM (SIE), y el padrón del SIUBEN. La cadena decía
  «Datos Abiertos RD», que no nombra ninguna cláusula. **El matiz que decide:** la ODbL
  distingue *Derivative Database* de *Produced Work* (§4.5). **Un informe o un gráfico es
  Produced Work y no dispara share-alike** — solo exige el aviso de atribución, que la
  plataforma ya computa e inserta sola. Lo que sí sería distribuir una base es servir la serie
  cruda a un consumidor **externo**, y para eso está la cuarentena verbatim — que **no aplica
  hoy**: la única llave viva de la Data API es SDQ-PMS, declarada `internal`, que interpreta el
  dato y no lo reexpide. El gate es de la llave, no del catálogo.
- ✅ **SISALRIL / CNSS — ODbL por decisión del dueño** (2026-08-23). Mismo tratamiento que el
  resto del portal: aviso de atribución sí, share-alike no sobre un informe. Queda registrado
  que la decisión NO se apoya en los términos del canal que el conector usa (`cnss.gob.do`,
  `redatam.sisalril.gob.do`) sino en el criterio del dueño.
- ✅ **SIS (primas y ramos) — ODbL verificado.** Los dos archivos que consumimos son, carácter
  por carácter, los **recursos CKAN** de los datasets `odc-odbl` «Primas Netas Cobradas según
  Ramo» y «Ramos de Compañías de Seguros»; el `sis.gob.do/wp-content` es sólo dónde el portal
  aloja el recurso. Aviso de atribución sí, share-alike no sobre un informe.
- ✅ **SIS (transparencia) — información pública dominicana, reutilizable con atribución.** Los
  estados financieros auditados y los índices de solvencia no están entre los cinco datasets
  ODbL del portal, pero eso no los deja sin régimen: **Ley 200-04**, **Decreto 103-22**
  (Política Nacional de Datos Abiertos, obligatoria para el Ejecutivo), **NORTIC A3** —que rige
  los sub-portales de transparencia— y **Ley 65-00 art. 41** para los actos administrativos. Y
  una cifra es un hecho: los hechos no son obra protegible. El «Todos los Derechos Reservados»
  del pie de `sis.gob.do` es plantilla de portal y **no fija el régimen del dato público** —
  contradice a un decreto que obliga a esa misma institución. Citar la fuente, sí; pedir
  permiso, no. Vale para el ISF y la solvencia por compañía.

> **Regla general para emisores públicos dominicanos.** La carga se invierte: **se presume
> reutilizable con atribución**, y lo que hay que declarar es la excepción. Un texto genérico
> de portal no es una excepción. No confundir con emisores extranjeros —UIT, CEPAL, Parline,
> EM-DAT, Comtrade—, donde sí rige lo que su licencia diga.
- ❌ **Nunca** describir una licencia restrictiva en prosa («uso público con cita») en un
  contrato, un deck o un informe. El texto de la licencia es además una entrada de máquina:
  `shared.data_api.manifest.license_restricts_redistribution` decide si el dato se reexporta
  buscando las cláusulas (`NC`, `SA`, `ODbL`) **en esa cadena**. Prosa amable = restricción
  invisible = activo publicable que no debía serlo.

**Estado de la verificación:** `shared.data.licenses.deuda_de_verificacion()` lista las fuentes
cuya licencia **nadie contrastó todavía** contra el emisor. La lista se computa; no se
escribe. Una fuente que figure ahí no está autorizada por omisión — y tampoco se puede
presumir que esté bien: de las **catorce** resueltas hasta ahora, **diez estaban
subdeclaradas** y **una sobre-declarada**. Antes de comprometer una fuente en una propuesta,
mirá si está verificada — y en las dos direcciones: la subdeclarada te expone, la
sobre-declarada te hace regalar un dato que sí podías usar.
