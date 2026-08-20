# Handoff — Construcción del "SDQ Outlook" de MIP (RD)

> **Procedencia.** Rescatado el 2026-08-20 de un stash sin commitear del 2026-08-04
> (`WIP on main: b8af4c6`), donde estaba como archivo NO RASTREADO — nunca llegó a `main` y
> por eso no aparecía en ninguna búsqueda del repo. **El documento va tal cual se escribió,
> sin editar.**
>
> **Validado parcialmente contra el servicio el 2026-08-20.** Lo que se comprobó y lo que
> NO, porque la diferencia decide qué se puede construir encima:
>
> **Confirmado.** El host responde y es SDQ-PMS (`title: "SDQ-PMS API"`,
> `description: "Backend del SDQ-PMS™ (proprietary)"`, release `2464f585`) — la URL de
> Railway sigue apuntando a donde este documento dice. Las **cinco rutas existen** y las
> cinco devuelven `503 · "El contrato de datos Outlook no está disponible."`, o sea el gate
> descrito en §2, cerrado como corresponde. El **orden de los candados también coincide**:
> con una API key inválida sigue dando 503 y no 401, así que el flag
> `SDQ_OUTLOOK_CONTRACT_LIVE` se evalúa primero.
>
> El 503 significa algo porque se probó contra un CONTROL: `/v1/outlook/inventado` devuelve
> `404 · Not Found`. Y este servicio responde JSON en `/`, no el HTML de un SPA — o sea que
> acá los códigos de estado son confiables, a diferencia de lo que pasa en MIP
> (en MIP una ruta inexistente devuelve 200 con el HTML del SPA, no 404, así que ahí un
> código de estado por sí solo no prueba nada).
>
> **NO verificado: los payloads.** Con el flag apagado no hay respuesta que mirar, así que
> todas las formas que describe §2 (`{time, ml_mode, universe_size, ...}`) siguen sin
> comprobar.
>
> **Y hay poco contra qué comprobarlas.** El `openapi.json` del servicio declara los cinco
> `200` como `object` **sin tipar**, no publica `security`, y solo lista `200` y `422` — el
> 503/401/403 que de hecho gobiernan el acceso no están en el esquema. Consecuencias para
> MIP: no se puede generar un cliente desde la spec, y si PMS renombra un campo no rompe
> nada del lado de ellos — rompe dentro del informe de MIP. Es el patrón que este repo ya
> pagó varias veces (un binding a algo inexistente no falla, DESAPARECE), ahora en la
> frontera entre dos plataformas.
>
> **Antes de escribir una línea contra este contrato**, pedirle a PMS que (a) tipe las cinco
> respuestas y (b) declare los códigos de la puerta en el OpenAPI. Sin eso la integración no
> tiene contrato, tiene prosa. Y para que devuelva datos hacen falta los tres pasos de
> activación que lista §2, que los ejecuta el owner del lado PMS.

---

> **De:** SDQ-PMS (lado plataforma / mercados globales)
> **Para:** SDQMIP (lado inteligencia RD)
> **Fecha:** 2026-07-23
> **Estado del lado PMS:** el programa Outlook de PMS está COMPLETO (Fases 1–6). El contrato de datos que MIP consume está construido y desplegado, gated (apagado hasta que MIP lo consuma).

Este documento es la guía general para que MIP construya **su propio Outlook**, el informe para consumidores/empresas de RD. No es una copia del de PMS: es el gemelo del otro lado del contrato compartido.

---

## 1. El norte (no negociable)

El edge del programa **no** es out-StoneX en commodities. Es el matrimonio de dos cosas que nadie más junta:

1. **Los mercados globales de SDQ-PMS** — señal cuantitativa + fundamentales públicos (USDA, EIA, FRED, NOAA, CFTC, USGS).
2. **La inteligencia propietaria de RD de SDQMIP** — lo que MIP ya tiene y nadie más tiene.

El Outlook de MIP es el que **lidera con RD** y usa lo global como telón de fondo. El de PMS es al revés (lidera global, RD como lente). Misma data, dos lecturas, dos audiencias (**D0**).

Reglas que NO se relajan, en ningún lado:

- **Todo grounded.** El modelo escribe SOLO sobre datos efectivamente traídos. Cero memoria de entrenamiento como fuente de un número.
- **Cada cifra citada** a su fuente y su fecha.
- **Nunca fingir un fundamental que no se tiene.** Si falta el dato, se declara la brecha; no se inventa.
- **Revisión humana obligatoria antes de publicar** (**D4**). Ningún análisis sale sin que una persona lo firme.

---

## 2. Qué expone PMS: el contrato `/v1/outlook`

PMS ya publica su capa global como API read-only. Es lo que MIP consume para la parte "mercados globales" de su informe. **No corre modelos ni ejecuta nada** — solo proyecta lo que PMS ya persistió.

Base URL prod: `https://api-production-764c.up.railway.app`

| Endpoint | Devuelve |
|---|---|
| `GET /v1/outlook/scan` | Último scan cuantitativo multi-clase terminado: `{ time, ml_mode, universe_size, scored_count, thesis, results }`. `ml_mode` suele ser SHADOW → el ranking es por z-score, no por probabilidad del modelo. |
| `GET /v1/outlook/signals?limit=&asset_class=` | Señales recientes del cerebro (proyección de feed, **sin** sizing ni provenance interno): `{ signals: [...], count }`. |
| `GET /v1/outlook/regime` | Régimen + sentiment agregados con citas reales: `{ window_days, decisions, regimes, sentiment, citations }`. |
| `GET /v1/outlook/committee` | Deliberaciones recientes del comité de 3 voces (Capa 3) donde **sí** hubo deliberación: `{ window_days, deliberations: [...] }`. Honesto: si no hubo, la lista viene vacía — no se fabrica postura. |
| `GET /v1/outlook/datapoints?commodity=&metric=&source=` | Datapoints fundamentales **vigentes** del almacén (frescura ya enforced): `{ datapoints: [{commodity, metric, value, unit, period, source, as_of, valid_until, methodology_note}], count }`. |

### Autenticación

Cada request lleva la API key en un header:

```
X-API-Key: <la key de servicio de MIP>
```

(o `Authorization: Bearer <key>` — cualquiera de las dos).

La puerta tiene tres candados, en orden:

1. **Flag `SDQ_OUTLOOK_CONTRACT_LIVE`** — si está off, TODO el contrato responde `503`. Default: off.
2. **API key válida** — sin ella `401`.
3. **Entitlement `outlook_contract`** en el workspace de la key — sin él `403` (una feed key comercial cualquiera **no** abre este contrato).

### Activación (lado PMS — lo hace el owner cuando MIP esté listo para consumir)

1. Emitir una **feed API key de servicio** para MIP (`/dashboard/admin/feed`).
2. Conceder el entitlement **`outlook_contract`** al workspace de esa key (comp por UI).
3. Prender el flag **`SDQ_OUTLOOK_CONTRACT_LIVE`** (`/dashboard/admin/flags`).

Hasta que MIP no tenga su consumo listo, esto queda apagado a propósito.

> **Nota importante sobre la data RD:** MIP **no** obtiene su data de RD desde PMS. MIP **es** la fuente de esa data (PMS de hecho la consume de MIP vía la Data API de MIP + webhooks). El contrato `/v1/outlook` es solo para la capa **global**. En el Outlook de MIP, RD viene de MIP directo y global viene de este contrato.

---

## 3. La arquitectura de generación que MIP debería espejar

PMS construyó y probó en producción un pipeline entero de "datos → documento firmado". MIP puede reusar el mismo esqueleto; está validado y las lecciones ya se pagaron. Las piezas, en orden:

### 3.1 Dossier cerrado (el universo citable)
Antes de invocar al modelo se arma un **dossier**: el conjunto EXACTO y cerrado de datos que el modelo puede citar (datapoints vigentes + lecturas + contexto). El modelo no ve nada más. Se **persiste junto con la sección** para auditoría. Regla de oro: si un número no está en el dossier, no puede aparecer en el texto.

### 3.2 Generación grounded → JSON estricto
El modelo escribe cada sección con reglas duras (solo el dossier, cada cifra citada, dirección solo con sustento). Devuelve JSON estricto que se valida. Si el dossier es pobre, el resultado honesto es "sin llamado direccional" — eso **no** es una falla, es integridad.

### 3.3 Voto por consenso (reproducibilidad)
La llamada direccional se corre **3 veces** y se exige **unanimidad** para emitir dirección. Sin unanimidad → "lateral" con la confianza más baja. Aprendido a los golpes: bajar temperatura no alcanza, mayoría simple no alcanza — solo la unanimidad dio reproducibilidad. (Costo: son 3 llamadas por sección; hay que medirlo, ver 3.6.)

### 3.4 Validador de citas (anti-alucinación)
Después de generar, un validador busca **cada cifra del texto en el dossier**. Las que no aparecen se marcan para el revisor. **Informa, no bloquea** — una derivación legítima (un ratio, una variación) es indistinguible de una invención para una máquina, y bloquear entrenaría al revisor a ignorar la alarma. Se recalcula en cada edición humana y al firmar; el conteo de no verificadas entra a la firma WORM.
> Lección cara: un validador se calibra **contra textos reales**, no contra intuición. El primero de PMS dejaba pasar 37% de cifras inventadas Y marcaba derivaciones legítimas. Principios que lo arreglaron: la precisión escrita ES la afirmación (`275,3` → ±0,05); una escala sin declarar no es escala; una derivación legítima muestra su trabajo (los insumos se buscan en la vecindad); **y el texto se lee en español** (conviven `1.327,7` y `1,327.7`) — esto último le pega directo a MIP.

### 3.5 Cola de revisión + firma WORM (D4)
Máquina de estados `draft → in_review → approved`. La primera edición humana snapshotea el borrador original de la IA (diff auditable humano-vs-IA). **Aprobar = firma WORM** hash-chained con el sha256 del contenido exacto firmado, quién y cuándo. `approved` congela la sección.

### 3.6 Salvaguardas de publicación (Fase 6)
- **Frescura al publicar:** entre generar y firmar pasan días; se re-consulta la vigencia de las citas al ensamblar y no se publica con datos vencidos.
- **Costo:** cada sección son N llamadas al modelo (ver 3.3); se acumula y se expone el gasto del mes. No dejar que aparezca recién en la factura.

### 3.7 Distribución (Fase 5)
Ensamblar y publicar son **actos distintos**. Alcances acumulativos: **interno → clientes (con entitlement) → público (resumen)**. Publicar deja evento WORM; retirar también. El resumen público muestra la estructura y la dirección, **nunca** el análisis ni las cifras.

---

## 4. Qué es distinto para el Outlook de MIP

- **Audiencia:** consumidores/empresas de RD, no inversionistas globales. El framing, el vocabulario y el "¿y esto a mí qué?" cambian.
- **Orden de la narrativa:** RD adelante (inflación, tipo de cambio, tasas, reservas, sectores locales), y lo global como fuerza externa que explica o presiona a RD — no al revés.
- **Fuente de RD:** nativa de MIP (MIP ya tiene su almacén, sus series, su IRMP, sus forecasts). El contrato de PMS solo aporta el telón global.
- **Idioma:** español, siempre. (Ver la lección del validador en 3.4.)
- **Distribución:** MIP decide sus propios alcances y su propio riel de cobro; la mecánica (publicar ≠ ensamblar, WORM, resumen público) es la misma que 3.7.

---

## 5. Checklist para arrancar

**Lado MIP (construcción):**
- [ ] Definir el catálogo de secciones del Outlook RD (qué complejos/indicadores locales + qué bloques globales).
- [ ] Armar el dossier cerrado por sección: RD (nativo) + global (del contrato `/v1/outlook`).
- [ ] Espejar el pipeline: dossier → generación grounded → JSON → validador de citas → cola de revisión → firma WORM.
- [ ] Reusar los principios del validador **en español** desde el día uno (no re-pagar la calibración).
- [ ] Consumo higiénico del contrato de PMS: cachear, no martillar (los datos globales cambian a lo sumo diario).
- [ ] Ensamblado + distribución con alcances propios.

**Lado PMS (activación, cuando MIP esté listo):**
- [ ] Emitir feed API key de servicio para MIP.
- [ ] Conceder entitlement `outlook_contract`.
- [ ] Prender `SDQ_OUTLOOK_CONTRACT_LIVE`.
- [ ] Smoke conjunto: MIP hace un `GET /v1/outlook/datapoints` real y recibe 200 con data.

---

## 6. Contexto que ayuda

- El plan y el estado del Outlook de PMS viven en el repo `sdq-pms-app`: `docs/plan-informe-fundamental.md` (plan normativo) y `docs/agent/status.md` (estado vivo).
- La data de RD que PMS consume de MIP ya está fresca y completa: 488 series, re-consulta limpia del 2026-07-23, y se mantiene sola (beat cada 12h + webhook firmado, vigencia 75 días).
- Decisiones LOCKED del programa: **D0** dos Outlooks / un contrato · **D2** cobertura completa (sin piloto) · **D3** ambas audiencias + cadencia trimestral/mensual · **D4** revisión humana obligatoria.
