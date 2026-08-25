# Instructivo — conectar los webhooks de SDQ·MIP a SDQ-PMS

Para el equipo de **SDQ-PMS**. Complementa [`GUIA_CONSUMO_DATA_API.md`](GUIA_CONSUMO_DATA_API.md)
(que cubre el consumo de datos); esto cubre solo los **avisos de dato nuevo**.

## 0. Dos credenciales distintas — no confundirlas

| Credencial | Para qué | Dirección | Estado |
|---|---|---|---|
| **Llave de API** (`sdq_live_lLQYHhkP_…`) | Autenticar las llamadas de PMS **hacia** la API | PMS → MIP | ✅ ya entregada |
| **Secreto de webhook** | Verificar la firma de los avisos que MIP envía **hacia** PMS | MIP → PMS | ⏳ se genera al registrar la URL |

La llave **no** sirve para verificar firmas, y el secreto **no** sirve para autenticar llamadas.
Guardar ambas por separado.

---

## 1. Qué construye PMS (antes de pedir el registro)

Un endpoint HTTPS público que acepte `POST`. Requisitos:

1. **Sin autenticación de sesión.** El aviso lo manda un servidor, no un usuario: no lleva JWT
   ni cookie ni `X-Workspace-Id`. ⚠️ **Ojo con el middleware de PMS**: si `require_workspace`
   o el guard de tenancy corre global, va a rechazar este endpoint con 401/403 y los avisos se
   perderán en silencio. Excluir explícitamente esta ruta.
2. **Responder 2xx rápido** (< 10 s, que es nuestro timeout). Encolar el trabajo y responder;
   no procesar de forma síncrona.
3. **Verificar la firma antes de hacer nada** (§3). Sin eso, cualquiera que descubra la URL
   puede hacer que PMS recalcule con un aviso falso.
4. **Ser idempotente**: el mismo evento puede llegar dos veces (p. ej. dos syncs seguidos).
   Procesar dos veces no debe duplicar nada.

Sugerido: `https://<dominio-pms>/api/webhooks/sdq-mip`

## 2. Intercambio con MIP (una vez)

1. PMS envía a MIP: **la URL** y **qué eventos** quiere (lista o `*`).
2. MIP registra y devuelve el **secreto**, que se muestra **una sola vez**.
3. PMS lo guarda como variable de entorno en Railway — nunca en el código:
   - `SDQ_MIP_API_KEY` = la llave de API (ya la tienen)
   - `SDQ_MIP_WEBHOOK_SECRET` = el secreto del webhook (nuevo)

Eventos disponibles: `macro.updated` · `irmp.updated` · `esg.updated` · `trade.updated` ·
`sector.updated` · `energy.updated` · `telecom.updated` · `tourism.updated` ·
`construction.updated` · `free_zones.updated` — o `*` para todos.

Para el arranque, recomiendo `macro.updated,irmp.updated` (es lo que PMS consume hoy) y ampliar
después: menos ruido mientras se estabiliza el receptor.

## 3. Qué recibe PMS

```
POST https://<dominio-pms>/api/webhooks/sdq-mip
Content-Type: application/json
X-SDQ-Event: macro.updated
X-SDQ-Signature: sha256=<hmac-sha256-hex del cuerpo con el secreto>
User-Agent: SDQ-Data-API-Webhook/1
```

```json
{
  "event": "macro.updated",
  "occurred_at": "2026-07-22T22:46:42.451251+00:00",
  "summary": {"period": "2026-06", "series_count": 315},
  "hint": "Consulte /api/data/v1/catalog/changes y los recursos afectados."
}
```

**El aviso NO trae el dato** — dice qué mirar. Tras verificar la firma, PMS vuelve por la API
con su llave. (Es deliberado: si el webhook trajera datos sería un segundo canal de acceso con
su propia superficie de permisos.)

## 4. Código del receptor (FastAPI, el stack de PMS)

```python
import os
from fastapi import APIRouter, Header, HTTPException, Request

from sdq_data_client import verify_webhook   # vendoreado desde clients/python/

router = APIRouter()
SECRET = os.environ["SDQ_MIP_WEBHOOK_SECRET"]


@router.post("/api/webhooks/sdq-mip")
async def sdq_mip_webhook(
    request: Request,
    x_sdq_signature: str = Header(default=""),
    x_sdq_event: str = Header(default=""),
):
    raw = await request.body()          # el cuerpo CRUDO: la firma es sobre estos bytes
    if not verify_webhook(SECRET, raw, x_sdq_signature):
        raise HTTPException(status_code=401, detail="firma inválida")

    # Encolar y responder rápido — nada síncrono acá.
    enqueue_refresh_sdq_mip(event=x_sdq_event)
    return {"ok": True}
```

⚠️ **Firmar sobre el cuerpo crudo**: si se parsea el JSON y se re-serializa, el orden de las
claves cambia y la firma no valida. Usar `await request.body()`, no `await request.json()`.

## 5. El respaldo — NO OMITIR

**El envío es un solo intento, sin reintentos.** Si el endpoint de PMS está caído o desplegando
cuando el evento se dispara, ese aviso **se pierde** (queda como fallido en nuestra bitácora,
pero no se reenvía). Tras 10 fallos seguidos el webhook se desactiva solo.

Por eso el diseño correcto es:

- **Webhook** = despertador, para refrescar rápido.
- **`GET /catalog/changes?since=<última corrida exitosa>`** en un job periódico (cada 6–12 h)
  = la red de seguridad. Es idempotente y no pierde nada.

Si PMS confía solo en el webhook, un deploy suyo durante una publicación del BCRD deja un hueco
silencioso en los datos.

## 6. Verificación conjunta (cuando el endpoint esté arriba)

1. MIP dispara un evento de prueba y PMS confirma que llegó y que la firma validó.
2. MIP revisa la bitácora: `GET /api/v1/admin/data-api/webhooks/{id}/deliveries` — muestra
   código HTTP, error y momento de cada intento. Es lo que responde "¿por qué no me llegó?".
3. Probar el camino infeliz: PMS devuelve 500 a propósito una vez y se confirma que queda
   registrado como fallo (y que el contador de fallos consecutivos sube).

## 7. Rotación y baja

- **Rotar el secreto**: se da de baja el webhook y se registra de nuevo (`DELETE` + `POST`);
  se emite un secreto nuevo. No hay rotación en caliente: coordinar una ventana.
- **Revocar la llave de API de PMS silencia también sus webhooks** — no hace falta acordarse
  de borrarlos por separado.
