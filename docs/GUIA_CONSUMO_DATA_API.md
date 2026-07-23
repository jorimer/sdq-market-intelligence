# Guía de consumo — SDQ Data API (`/api/data/v1`)

Para un sistema cliente (el primero: **SDQ-PMS**). Autosuficiente: se puede pegar en una
sesión sobre el repo del cliente sin más contexto.

- **Base URL (prod):** `https://sdq-market-intelligence-production.up.railway.app/api/data/v1`
- **Autenticación:** header `Authorization: Bearer <llave>` (o `X-API-Key: <llave>`).
  La llave tiene la forma `sdq_live_<prefix>_<secret>`; no expira salvo revocación.
- **Términos (llave `usage=internal`):** el dato es **insumo de análisis propio** — se usa
  para calcular e interpretar; no se reexpone tal cual a terceros. Al citar, atribuir a
  SDQ Market Intelligence **y** a la fuente primaria que declara cada activo.

## Contrato general

Toda respuesta es `{meta, data, caveats}`:

- `meta` — `generated_at`, `client_ref`, `usage`, `quota` (consumo del período) y la
  licencia de uso. En cada recurso, además, el descriptor del activo servido.
- `data` — el payload. **Un faltante viaja como `null` con `reason`; nunca se interpola
  ni se asume cero.**
- `caveats[]` — advertencias estructuradas (`{code, message}`). Programar contra `code`.

Errores: cuerpo `{detail: {code, message, message_en}}` — programar contra `code`, el
texto puede cambiar. Relevantes: `missing_key`/`invalid_key`/`key_revoked` (401),
`series_not_found`/`score_not_found` (404 — también cubre "sin acceso": no se distingue),
`ambiguous_code` (400), `as_of_unsupported` (422), `rate_limit`/`quota_exhausted` (429,
respetar el header `Retry-After`).

## ⚠️ Orden de las colecciones — leer esto antes de indexar

La API tiene **dos órdenes distintos**, y cada respuesta lo declara en `meta.order`:

| Recurso | `meta.order` | El más reciente está en |
|---|---|---|
| `/series` | `period_asc` | **`data[-1]`** (último) |
| `/scores` (con `subject`) | `period_desc` | **`data[0]`** (primero) |
| `/forecasts` | `period_desc` | **`data[0]`** (primero) |
| `/scores` (sin `subject`) | — | cada fila ya ES el vigente de su sujeto |

**Nunca asumir el orden: leer `meta.order`.** Aplicar el patrón de `/series` a `/scores`
devuelve el valor MÁS ANTIGUO en silencio — sin error, sin aviso, solo un número viejo
que parece bueno. (Pasó en la integración real: PMS leyó `data[-1]` del IRMP y obtuvo el
score de 2016 creyendo que el índice estaba desactualizado.)

Para el valor vigente de un score, la forma segura no es indexar sino leer
**`meta.latest`** (presente cuando se consulta con `subject`), que trae `{subject, period,
score, band}` ya resuelto.

## El patrón correcto: descubrir, no cablear

El inventario **crece solo** (auto-extensión): series y scores nuevos aparecen sin aviso.
No cablear listas de códigos — descubrirlos:

```
GET /catalog                    → todo lo visible para la llave
GET /catalog?kind=series        → solo series
GET /catalog?kind=score         → solo scores/índices
```

Cada activo trae `code`, `sector_key`, `label`, `frequency`, `n_obs`, `period_first/latest`,
`source`, `license`, `derivation` (`verbatim` = valor del emisor normalizado; `derived` =
cálculo de SDQ) y `stability` (`thin` = historia corta: no meterlo a un modelo sin mirar).

## Recursos

### Series canónicas normalizadas

```
GET /series?code=<code>[&sector=][&start=][&end=][&as_of=][&limit=]
```

Observaciones ordenadas por período, con `unit`, `source` y `published_at` por fila.
`as_of` (ISO) es **point-in-time real**: corta por fecha de publicación del emisor; si la
serie no tiene ese linaje devuelve **422** — jamás datos de hoy con etiqueta vieja.
Períodos: `2025` (anual), `2025-Q1` (trimestral), `2025-01` (mensual).

### Scores e índices propietarios (F2)

```
GET /scores/{sector}[?code=][&subject=][&start=][&end=][&limit=]
```

Cálculo de casa con **desglose dimensional numérico** (`{dimension: {score, weight,
contribution}}`). La narrativa no viaja — es el producto de reporte. Sin `subject` =
panel (último valor por sujeto); con `subject` = trayectoria **en orden descendente**
(`data[0]` es el vigente; o usar `meta.latest`, que lo resuelve sin indexar). **`subject` se toma del
campo `subjects` del descriptor** (`/catalog?kind=score`) — no asumir formato ISO: el
panel IRMP usa códigos de 2 letras (`DO`, `PE`), el IRC usa ISO3 (`DOM`, `JAM`).
**Atención a `direction` en el descriptor**: en el IRMP mayor score = MENOR riesgo.

`meta.periods_available` lista **todo** el histórico del score (no solo lo filtrado en
la consulta). Si la trayectoria tiene años faltantes, viaja además el caveat
**`sparse_trajectory`** con los períodos ausentes: **no interpolar ni unir los puntos**
como si fuera una serie completa — un período ausente no se computó, no vale cero.

**Comparabilidad entre períodos.** Estos índices son **panel-relativos**: cada variable se
normaliza min-max contra el conjunto de pares del período. Por eso cada observación trae
`peer_set_size`, y si los períodos servidos usaron paneles de distinto tamaño viaja el
caveat **`panel_size_varies`**: esos valores están en la misma escala pero **no significan
lo mismo**, y compararlos como una tendencia es un error. Es la trampa más silenciosa de
un índice comparado — el número se ve perfectamente normal.

Publicados hoy: `macro`→`irmp` (riesgo macro-político, panel de países) ·
`esg`→`irc` (resiliencia climática, panel Caribe/LatAm). El resto aparece en el
catálogo cuando cada sector lo declare.

### Señales deterministas (F2)

```
GET /signals/{sector}
```

Salida del motor de reglas (alerta temprana, precursores): `key`, `label`,
`severity` (`info|watch|alert`), `period`, `detail`. **Lista vacía = sin señal activa —
es un resultado, no un hueco.** Sin narrativa: el veredicto es determinista y citable.

### Pronósticos con track record (F3)

```
GET /forecasts/{sector}[?code=][&limit=]
```

Cada pronóstico se **congela antes del hecho** y se puntúa contra la publicación oficial;
nunca se reescribe uno pasado. `meta.forecast` trae el track record acumulado (acierto,
Brier) **y la línea base** contra la cual esas cifras significan algo. `status` distingue
el pronóstico vigente (`pending`, sin resultado aún) del histórico (`scored`).

**Leer el caveat `small_sample`**: con pocas observaciones puntuadas, una tasa de acierto
alta no es informativa. Publicado hoy: `macro`→`tpm` (dirección de la próxima decisión de
la Junta Monetaria del BCRD).

### Calidad y procedencia (F2)

```
GET /quality/{sector}
```

El mismo registro que gobierna el gate de honestidad interno: `coverage_real` (fracción
del peso del índice anclada a dato real), estado por variable (`real|rubric|gap`),
`scope` (`national` = dato real de país, idéntico para todos los sujetos — no diferencia
entre ellos) y el párrafo `provenance` generado. **Consultarlo antes de meter un eje a un
modelo**: dice cuánto del índice es dato y cuánto supuesto declarado, hoy.

### Cambios del inventario (F3)

```
GET /catalog/changes?since=<ISO>
```

Altas y bajas desde esa fecha. **Llamarlo en cada corrida**: el inventario crece solo, y
una serie que *dejó* de publicarse rompe un modelo en silencio si nadie la reporta. Una
fecha ilegible devuelve 422 (`invalid_since`) en vez de "sin cambios" — silencio y
"no pasó nada" no deben confundirse.

## Avisos por webhook (F3) — dejar de sondear

En vez de preguntar cada hora si el BCRD publicó, SDQ avisa cuando el snapshot se
recalcula. Para registrar un endpoint, pedirlo al administrador de MIP (`POST
/api/v1/admin/data-api/webhooks` con `api_key_id`, `url` https y `events`).

- El aviso **no trae el dato**: solo `{event, occurred_at, summary, hint}`. Tras
  verificarlo, el cliente vuelve por la API con su llave. Así el webhook no se convierte
  en un segundo canal de acceso con su propia superficie de permisos.
- **Verificar SIEMPRE la firma** del header `X-SDQ-Signature` (HMAC-SHA256 del cuerpo con
  el secreto entregado al registrar). Una URL de webhook es pública por naturaleza: sin
  firma, cualquiera que la adivine puede hacer que su sistema recalcule con un aviso falso.
- Eventos: `macro.updated`, `irmp.updated`, `esg.updated`, `trade.updated`,
  `sector.updated`, `energy.updated`, `telecom.updated`, `tourism.updated`,
  `construction.updated`, `free_zones.updated` (o `*`).
- Tras 10 fallos seguidos el webhook se desactiva solo; la bitácora de entregas queda
  disponible para diagnosticar.

## SDK Python (F3)

[`clients/python/sdq_data_client.py`](../clients/python/sdq_data_client.py) — **un archivo,
pensado para copiarse dentro del repo del cliente**; única dependencia: `httpx`. Trae
backoff que respeta `Retry-After`, errores tipados con `code` estable, y
`verify_webhook()` para el receptor.

```python
from sdq_data_client import SdqDataClient

sdq = SdqDataClient(api_key=os.environ["SDQ_MIP_API_KEY"])
for asset in sdq.catalog(kind="series"):        # descubrir, no cablear
    ...
obs = sdq.series("bcrd.inflacion.inflacion.interanual", start="2024-01")
irmp = sdq.scores("macro", subject="DO")
fc = sdq.forecasts("macro")                     # respuesta completa: el track record
                                                # vive en meta y los avisos en caveats
```

## Receta de integración para SDQ-PMS

1. **Conector nuevo** en `apps/api/src/sdq_api/connectors/` (patrón de los existentes:
   cliente `httpx` por llamada, errores a `ConnectorError`/`NetworkError`). Llave por
   variable de entorno (`SDQ_MIP_API_KEY`) en Railway — nunca en el código.
2. **Primer caso de uso:** reemplazo del agregador FX/macro. Descubrir por `/catalog` las
   series BCRD (inflación, tipo de cambio, reservas, TPM) y consumirlas con linaje.
   **Decisión del dueño: correr en PARALELO con el conector `bcrd` actual
   (open.er-api.com) durante un trimestre, comparando valores** — divergencia se reporta,
   no se resuelve en silencio.
3. **Contexto país para el Outlook/cerebro:** `GET /scores/macro?subject=DO` (IRMP con
   dimensiones) y `GET /signals/macro` (alertas macro deterministas).
4. **Higiene de consumo:** registrar un webhook y refrescar por aviso en vez de sondear;
   como respaldo, cachear respuestas ≥1h (las fuentes publican con cadencia
   mensual/trimestral — martillar no trae dato nuevo); respetar `Retry-After` en 429;
   registrar `meta.generated_at` con cada valor almacenado; tratar `stability: "thin"` y
   los `caveats` como parte del dato, no como ruido.
5. **Cortafuegos de honestidad (regla SIMV):** si un valor que PMS va a mostrar o usar en
   una recomendación vino con `reason` (faltante) o de una serie `thin`, esa condición
   viaja con él aguas abajo.

## Operación (lado MIP)

- Emitir/rotar llaves: `railway ssh "python scripts/issue_data_api_key.py"` (env
  `DATA_API_KEY_*`). Revocar: `POST /api/v1/admin/data-api/keys/{id}/revoke` (admin).
- Uso y auditoría por llave: `GET /api/v1/admin/data-api/keys/{id}/usage`.
- Qué está retenido y por qué: `GET /api/v1/admin/data-api/manifest` (interno).
