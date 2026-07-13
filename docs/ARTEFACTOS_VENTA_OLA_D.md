# Artefactos de venta — Ola D / PR-12 (2026-07-13)

Cierre del PR-12 del plan de remediación post-DD. Los archivos binarios NO se
commitean (repo público): quedan en `data/artefactos_venta/` de la máquina del
dueño y se regeneran con los comandos de abajo.

## 1 · Reportes Single-Entity de banca (muestras)

Generados desde **producción** (dato real SIB, período 2026-03-31, narrativa
Cerebro con guardrail numérico), tier `deep_dive`, cuenta enterprise:

| Muestra | Archivo local | Páginas |
|---|---|---|
| Banco de Reservas de la República Dominicana (SDQ-AA · 86.7/100) | `data/artefactos_venta/SDQ_DeepDive_Banca_Banreservas.pdf` | 14 |
| Banco Múltiple Lafise | `data/artefactos_venta/SDQ_DeepDive_Banca_Lafise.pdf` | 15 |

Regenerar (con token de una cuenta enterprise):

```
GET /api/v1/products/banking/deep_dive/download?scope=<uuid>&format=pdf
  Banreservas: b9e54e9b-a36b-409d-b738-6d390dcd9f40
  Lafise:      6bea879c-6a90-42f6-acc5-b7d1e352ddd2
```

## 2 · Tarifario provisional v0.2 (DOCX)

`data/artefactos_venta/SDQ_MIP_Tarifario_PROVISIONAL_v0.2.docx`, generado por
`scripts/build_tarifario_docx.py` sobre el catálogo REAL de SKUs de prod
(30 SKUs: 14 sectores × insight/deep_dive + all_access + enterprise).

- **Todos los precios son PROPUESTA** para calibración del dueño, salvo el ancla
  ya decidida `special:research-custom` = US$3,500/encargo (provisional).
- Nada rige hasta publicarse en `/admin/tarifario` (tabla `Tariff`).
- Estructura propuesta: Insight US$149/mes · US$1,490/año por sector; Deep Dive
  US$450/informe; All-Access US$690/mes; Enterprise US$1,450/mes.

## 3 · E2E checkout PayPal sandbox — BLOQUEADO por brecha de servicio

Verificado contra prod (2026-07-13). El código está listo (sandbox/live por
config, breakdown ITBIS, captura sin webhook), pero el flujo no puede correrse
de punta a punta porque faltan insumos del dueño:

| Precondición | Estado en prod |
|---|---|
| Credenciales PayPal (`/admin/pagos`) | `env=sandbox`, `clientId` cargado, **`enabled=False`** (falta el secret o activar el flag) |
| Billing plans por SKU+intervalo (`paypal_plans`) | **Vacío** → suscripciones darían 503 |
| Precios publicados (tabla `Tariff`) | **Cero tarifas** → `POST /billing/checkout/order` responde 400 «Este producto no tiene precio configurado» (verificado) |

Pasos del dueño para desbloquear (después el E2E corre completo):
1. `/admin/pagos`: completar el Secret sandbox y habilitar la pasarela.
2. Crear los billing plans (sku × intervalo) en el dashboard sandbox de PayPal y
   cargarlos en `/admin/pagos`.
3. Publicar el tarifario aprobado en `/admin/tarifario` (partir del docx v0.2).
4. Aprobar un pago con la cuenta *buyer sandbox* (guía completa en
   `docs/E2E_PAYMENTS_PAYPAL_TEST_PROMPT.md`).
