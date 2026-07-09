# Prompt — Prueba E2E de Pagos + PayPal (suscripción, impuestos, cancelación, factura)

> Pega este documento como primer mensaje de una sesión de Claude Code sobre el repo
> `sdq-market-intelligence`. Es una prueba integral del subsistema de pagos: verifica lo
> que ya existe **y construye lo que falta** (impuestos, copy, factura), resolviendo cada
> hallazgo dentro de la corrida con la política fix→PR→espera OK.

---

## 0. Misión

Probar de extremo a extremo el **flujo de pago con PayPal** de SDQ·MIP —compra puntual y
suscripción— en las **cuatro dimensiones** del estándar E2E (funcionalidad · correctitud ·
adecuación al nivel · cobertura), y **cerrar los requisitos de negocio del dueño** (§4).
Todo hallazgo se resuelve en la corrida; las únicas brechas que pueden quedar abiertas son
**legales** o de **servicio por contratar** (p. ej. credenciales/planes que el dueño debe
cargar, o una decisión fiscal que requiere su confirmación).

El subsistema vive en `shared/billing/` (router `/api/v1/billing`) + `shared/products/`
(acceso/entitlements) + `frontend/src/modules/platform/` (catálogo, checkout, Mi Plan,
/admin/pagos). El proveedor es PayPal (`shared/billing/providers/paypal.py`, httpx puro).

---

## 1. Entorno y credenciales

- **Recorrido:** producción en vivo (Railway), pero **el flujo de pago se prueba primero en
  SANDBOX de PayPal** (mover dinero real está fuera de alcance). El env se controla por
  config en `/admin/pagos` (`shared/settings/service.py:get_paypal_config`, campo `env`
  sandbox/live).
- **Precondición del dueño (posible brecha de servicio):** el flujo E2E de pago requiere
  que estén cargadas en `/admin/pagos` las **credenciales sandbox de PayPal** (Client ID,
  Secret, Webhook ID) y los **billing plans** por SKU+intervalo (el `plan_id` recurrente se
  crea en el dashboard de PayPal). Si faltan, el checkout de suscripción devuelve 503
  "Falta el billing plan de PayPal". Verifica su estado ANTES de probar; si faltan,
  levántalo como brecha de servicio y usa cuentas sandbox de comprador/vendedor de PayPal.
- **Cuentas de la app:** admin `claude@sdqconsulting.com.do / Claude1234` (config, tarifario,
  webhooks) y un usuario de cliente para comprar/suscribir (crear uno free y llevarlo por el
  flujo). Para verificar acceso post-pago, `reporting-qa@ / Reporting1234` (enterprise).
- **Cuentas sandbox de PayPal:** usa el **buyer sandbox** de PayPal para aprobar el pago y el
  **business sandbox** como receptor; desde el dashboard de PayPal sandbox se puede además
  **cancelar la suscripción** para probar el lazo de cancelación (§3.D).
- **Arreglos:** en local/dev con test de regresión; verificación del flujo en sandbox
  (approval real de PayPal en su UI) + verificación de las superficies in-app en prod.
- Intérprete Python: `/opt/anaconda3/bin/python`. Paridad dev↔prod (SQLite/Postgres).

---

## 2. Reglas de operación

1. **El dinero es sagrado.** Cualquier cambio que toque el MONTO que se le envía a PayPal
   (§3.C impuestos) se prueba en sandbox de punta a punta antes de PR, y **nunca se ejecuta
   contra live sin OK explícito**. No se cobra de verdad en ninguna prueba.
2. **Correctitud fiscal.** El desglose suscripción/impuesto/total debe cuadrar al centavo;
   redondeo consistente; moneda explícita. Si hay duda sobre la tasa o la exención, se
   pregunta al dueño (ver §4, nota fiscal), no se asume.
3. **Fix → PR → espera OK antes de mergear/desplegar.** Verificar cada superficie (no
   extrapolar). Excelencia sobre velocidad.
4. **Idempotencia y seguridad:** los webhooks verifican firma y deduplican
   (`BillingEvent`); no romper eso. No loguear secretos (se guardan encriptados).

---

## 3. Alcance — verificar lo que existe y construir lo que falta

### 3.A — Flujo de pago actual (VERIFICAR en sandbox)
Recorrer el happy-path completo con PayPal sandbox:
- **Compra puntual (Deep Dive):** `POST /api/v1/billing/checkout/order {sku:"deep_dive:{sector}"}`
  → `approval_url` → aprobar en PayPal (buyer sandbox) → retorno a
  `/checkout/return?token=...` (`CheckoutReturnPage.tsx`) → captura
  `POST /billing/checkout/order/capture` → webhook `order_paid` →
  `grant_entitlement(source='order')` → el cliente ve el Deep Dive.
- **Suscripción (Insight):** `POST /billing/checkout/subscription {sku:"insight:{sector}", interval}`
  → `approval_url` → aprobar → retorno con `subscription_id` → webhook
  `BILLING.SUBSCRIPTION.ACTIVATED` → `apply_subscription(active)` → el cliente ve el Insight
  del sector; `active_subscription_tier()` lo refleja en Mi Plan.
- **Verificar:** el acceso se concede realmente (probar una ruta de producto con
  `require_product_access`), el webhook se procesa una sola vez (idempotencia), y el estado
  se refleja en `/mi-plan`.

### 3.B — Copy de checkout: PayPal + pantalla de aprobación (CONSTRUIR — requisito del dueño)
Hoy los botones dicen "Comprar"/"Suscribirme" a secas (`ProductCatalogPage.tsx`) y no
informan el medio de pago ni el redireccionamiento. Implementar (ver criterios exactos §4):
- Antes de disparar el checkout, el cliente debe saber que **el pago es con PayPal** y que
  **será redirigido a una pantalla de PayPal para aprobar**.
- La superficie de confirmación/aprobación (el paso previo al redirect y/o
  `CheckoutReturnPage.tsx`) debe **indicar explícitamente que PayPal es el medio de pago**.

### 3.C — Impuestos: suscripción + impuestos, total a PayPal, desglose (CONSTRUIR — requisito del dueño)
Hoy **no hay cálculo de impuestos**: a PayPal se le manda `Tariff.amount` sin impuestos
(`router.py:75`, `providers/paypal.py:98-102`) y no hay factura. Implementar:
- **Cálculo:** `total = subtotal (suscripción) + impuesto`. La tasa (ITBIS RD 18%) debe ser
  **configurable**, no mágica en código; considerar la matriz fiscal SDQ (local vs
  exportación de servicios a cliente extranjero — puede ser exento; **confirmar con el dueño**,
  §4 nota fiscal).
- **A PayPal se le pasa el TOTAL** (suscripción + impuestos), no el subtotal. Ajustar
  `create_order_checkout` / `create_subscription_checkout` (nota: en suscripción PayPal el
  monto lo fija el `plan_id`; el plan de PayPal debe reflejar el total, o el impuesto se
  modela como parte del plan — resolver cómo se pasa el total en el modelo de suscripción de
  PayPal, no solo en el de orden).
- **En TODAS las superficies que muestran precio** (catálogo, botón de suscripción, Mi Plan,
  pantalla de aprobación) informar que es **"suscripción + impuestos"** con el desglose
  visible: `Subtotal $X + ITBIS $Y = Total $Z`.
- **Factura (desglose):** al momento de facturar, la factura al cliente **desglosa**
  suscripción vs impuestos (aunque a PayPal se le cobró el total). Nota: la generación de
  facturas **no existe hoy** (Fase 4) — evaluar alcance con el dueño: si se construye la
  factura aquí, reusar el skill/plantilla de factura SDQ (matriz fiscal RD); si no, dejar el
  modelo de datos listo (subtotal/impuesto/total persistidos por transacción) y marcar la
  factura como entrega siguiente.

### 3.D — Cancelación por PayPal → la app la ve → suspende acceso (VERIFICAR el lazo completo)
El webhook ya mapea `BILLING.SUBSCRIPTION.CANCELLED` / `EXPIRED` / `SUSPENDED` →
`apply_subscription(cancelled|expired)` (`webhook.py:35-78`, `paypal.py:187-193`), y
`can_access()` deja de conceder el tier si la suscripción no está activa/vigente
(`access.py:120-145`, `subscriptions.py:122-145`). **Verificar de punta a punta:**
- Cancelar la suscripción **desde el dashboard de PayPal** (lado cliente) → PayPal emite el
  webhook → la app lo recibe en `POST /billing/webhook/paypal`, verifica firma, deduplica,
  y marca la suscripción como cancelada.
- Confirmar que **el acceso se suspende** realmente: tras la cancelación, la ruta de producto
  del sector suscrito debe devolver 402 y `/mi-plan` debe reflejar la baja.
- Probar también `PAYMENT_FAILED` (pago recurrente fallido) y `EXPIRED` (fin de período sin
  renovar). Verificar que el gating por `current_period_end` funciona (una suscripción
  "active" con período vencido NO debe conceder acceso).
- **Cobertura:** ¿el cliente puede cancelar también desde la app (no solo en PayPal)? Si no
  existe, evaluar con el dueño si se agrega un botón "Cancelar suscripción" en Mi Plan que
  llame a la API de PayPal para cancelar y refleje el estado.

---

## 4. Requisitos explícitos del dueño (criterios de aceptación)

Redactados por el dueño; son condición de cierre:

1. **Al suscribirse debe indicarse que el pago es con PayPal y que llevará a una pantalla
   para aprobación.** (§3.B)
2. **Verificar que el cliente puede cancelar su suscripción por PayPal, y cómo la app lo ve
   y suspende el acceso.** (§3.D)
3. **En todos los lugares informar al cliente que será la suscripción + impuestos.** (§3.C)
4. **A PayPal se le pasa el monto total (suscripción + impuestos) para el cobro; al momento
   de facturar se desglosa en la factura para el cliente.** (§3.C)
5. **Donde se hace la aprobación para ir a PayPal debe indicarse que ese será el medio de
   pago.** (§3.B)

> **Nota fiscal (requiere confirmación del dueño antes de construir §3.C):** ¿la tasa es
> ITBIS 18% siempre, o depende del tipo de cliente (RD vs extranjero = exportación de
> servicios, posible exención)? ¿El precio del tarifario (`Tariff.amount`) es el subtotal
> pre-impuesto o ya incluye impuesto? La respuesta define el cálculo. NO asumir.

---

## 5. Registro de hallazgos (durante la corrida)

| # | Área (A/B/C/D) | Tipo (verificación/construcción) | Severidad | Descripción | Causa/estado | Acción | Estado (Resuelto / PR / Brecha legal-servicio) |
|---|---|---|---|---|---|---|---|

Severidad: Crítico (bloquea cobro/acceso) · Alto · Medio · Bajo.

---

## 6. Informe final

1. **Resumen ejecutivo:** salud del flujo de pago (compra + suscripción + cancelación) y
   estado de los 5 requisitos del dueño (§4).
2. **Tabla de hallazgos** con su resolución.
3. **PRs abiertos** esperando aprobación.
4. **Evidencia del flujo en sandbox:** capturas/valores de una compra, una suscripción y una
   cancelación→suspensión completas.
5. **Brechas remanentes — SOLO:** legales/servicio (credenciales o planes PayPal que el
   dueño debe cargar; decisión fiscal pendiente; SKU sin precio).
6. **Recomendación de despliegue** y, si aplica, el plan para pasar de sandbox a live.

---

## 7. Definición de "terminado"

- Flujo de compra y de suscripción recorridos en sandbox de punta a punta, con acceso
  concedido y reflejado en Mi Plan.
- Los 5 requisitos del dueño (§4) implementados y verificados: copy de PayPal + pantalla de
  aprobación, "+impuestos" en todas las superficies, total (sub+impuestos) a PayPal, y el
  lazo cancelación-por-PayPal → suspensión de acceso demostrado.
- Cada hallazgo: resuelto o con PR abierto esperando OK.
- Las únicas líneas abiertas son legales o de servicio por contratar, etiquetadas.
