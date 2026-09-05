# Proxy Cloudflare para fuentes detrás de un WAF

Algunos emisores protegen su API con un WAF que bloquea las IPs de datacenter. Desde Railway
la petición no llega; desde una laptop sí. Este Worker corre en el borde de Cloudflare, cuyas
IPs esos WAF sí aceptan, y reenvía:

```
Railway → Cloudflare Worker → emisor
```

**Vivía en otro repositorio** (`financial-analysis-agent`, la aplicación predecesora donde
nació el banking score). Se mudó acá el 2026-09-05 porque quien lo edita es esta plataforma, y
dos copias de un fuente que se despliega a mano es cómo se pierde un cambio.

## Quiénes van por acá

| Emisor | Host | Cómo se comprobó que hace falta |
|---|---|---|
| Superintendencia de Bancos (RD) | `apis.sb.gob.do` | WAF de Sucuri; bloquea las IPs de Railway |
| Comisión para el Mercado Financiero (Chile) | `api.cmfchile.cl` | Desde escritorio devuelve sus códigos propios (421/422); desde el datacenter, 500 con una página «Web Page Blocked!» de 39 KB |

## Agregar una fuente nueva

Son **dos** trabajos, y omitir el segundo es el defecto que ya nos pasó:

1. Declararla en `KNOWN_PROVIDERS` (`shared/settings/service.py`) con `needs_proxy: True`.
2. Agregar su host a `ALLOWED_TARGET_HOSTS` en `worker.js` **y desplegar**.

`shared/settings/tests/test_la_lista_del_worker_y_el_catalogo.py` exige el cruce, así que
olvidarse del paso 2 rompe CI en vez de romper producción. Lo que el test **no** puede
comprobar es el despliegue: commitear no despliega.

## Cómo lo consume la plataforma

El proxy es **global**, uno solo para todas las fuentes: se carga en Configuración → Fuentes de
Datos (URL del Worker + secreto), y `get_proxy_config()` lo resuelve. No hay proxy por fuente
—hubo uno y quedó su columna en la base—; ver el comentario en `test_connection()`, porque esa
columna vacía llegó a cancelar el proxy global.

## Qué significa cada código

Están elegidos para discriminar, y el backend los lee así:

| Respuesta | Quién la dio | Qué significa |
|---|---|---|
| `401` | el Worker | el secreto del proxy está mal. **La petición no salió.** |
| `403` | el Worker | el destino no está en `ALLOWED_TARGET_HOSTS`. **La petición no salió.** |
| cualquier código **con** `X-Proxy-Status` | el emisor | lo que ves es la respuesta real de la fuente |

Solo lo **reenviado** lleva `X-Proxy-Status`. Su ausencia en un error significa que el rechazo
es del Worker, no del emisor: de ahí sale `_has_proxy_relay()` en el backend. Sin esa
distinción, un 403 del proxy se lee como si lo hubiera dado la fuente y manda a revisar una
credencial que puede estar perfecta.

`ALLOWED_ORIGINS` es otra cosa y **no rechaza nada**: solo decide si se devuelve la cabecera
`Access-Control-Allow-Origin`. Nuestras llamadas salen de servidor a servidor y no mandan
`Origin`, así que esa lista es inerte para la plataforma. Sigue nombrando a la aplicación
predecesora; se dejó como estaba porque cambiarla no nos aporta nada y podría romperle el
navegador a esa app si todavía corre.

## Desplegar

```bash
cd infrastructure/cloudflare-worker-proxy && wrangler deploy
```

**Dos trampas, las dos comprobadas el 2026-09-05:**

1. **`CLOUDFLARE_API_TOKEN` en el entorno gana sobre el login.** Si está puesto, `wrangler
   login` se niega («Unset the CLOUDFLARE_API_TOKEN…») y `wrangler deploy` falla con
   `Authentication error [code: 10000]` si ese token no tiene permiso de escritura sobre
   Workers. Para usar OAuth de la cuenta: `unset CLOUDFLARE_API_TOKEN && wrangler login`.
2. **El editor del dashboard también sirve** (Workers & Pages → `sib-api-proxy` → Edit code →
   Deploy) y fue el camino que funcionó. Ojo: ahí se edita el **bundle**, no este fuente, así
   que hay que replicar el cambio en este archivo o el repo queda desfasado del Worker vivo.

El secreto **no** se pierde al desplegar: `PROXY_SECRET` está guardado del lado de Cloudflare.
Se carga una sola vez con `wrangler secret put PROXY_SECRET`.

## Costo

Plan gratuito: 100.000 peticiones por día. El consumo real de la plataforma es de tres dígitos.
El límite que sí aprieta es el del emisor —la CMF da 10.000 consultas **mensuales**— y ese se
administra del lado del conector, no acá.
