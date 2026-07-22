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
panel (último valor por sujeto); con `subject` = trayectoria. **`subject` se toma del
campo `subjects` del descriptor** (`/catalog?kind=score`) — no asumir formato ISO: el
panel IRMP usa códigos de 2 letras (`DO`, `PE`), el IRC usa ISO3 (`DOM`, `JAM`).
**Atención a `direction` en el descriptor**: en el IRMP mayor score = MENOR riesgo.

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

### Calidad y procedencia (F2)

```
GET /quality/{sector}
```

El mismo registro que gobierna el gate de honestidad interno: `coverage_real` (fracción
del peso del índice anclada a dato real), estado por variable (`real|rubric|gap`),
`scope` (`national` = dato real de país, idéntico para todos los sujetos — no diferencia
entre ellos) y el párrafo `provenance` generado. **Consultarlo antes de meter un eje a un
modelo**: dice cuánto del índice es dato y cuánto supuesto declarado, hoy.

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
4. **Higiene de consumo:** cachear respuestas ≥1h (las fuentes publican con cadencia
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
