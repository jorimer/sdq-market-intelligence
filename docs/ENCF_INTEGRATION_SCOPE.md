# Integración e-CF / e-NCF (DGII) — alcance

Facturación electrónica de la República Dominicana (Comprobante Fiscal Electrónico, e-CF).
Ref: `docs/Formato Comprobante Fiscal Electrónico (e-CF) v1.0.pdf` (DGII, v1.0, Oct 2025).

> **Estado:** el modelo de datos ya está **listo para enchufar** (columnas `encf_*` en
> `billing_transaction`; el tipo previsto se calcula al facturar). La emisión real contra la
> DGII es un **workstream de cumplimiento aparte** que requiere precondiciones de servicio/
> legales del dueño (certificado digital + enrolamiento DGII). No se construye hasta tenerlas.

## Qué ya quedó listo (en el PR de pagos)
- `billing_transaction.encf_type` — tipo de e-CF previsto, calculado por la matriz fiscal:
  - **31** Factura de Crédito Fiscal Electrónica — cliente local (RD) **con RNC** que necesita crédito fiscal.
  - **32** Factura de Consumo Electrónica — consumidor final local (default actual, no capturamos RNC del cliente todavía).
  - **46** Comprobante de Exportaciones Electrónico — cliente del exterior (exportación de servicios, exento de ITBIS).
- Columnas vacías a llenar al emitir: `encf_number` (e-NCF), `encf_status`, `encf_trackid`
  (TrackID del acuse), `encf_security_code`, `encf_signed_at`.
- La factura PDF ya muestra el e-NCF + tipo cuando existan; sin e-NCF sale como **comprobante
  interno** (no válido como crédito fiscal).

## Precondiciones (dueño — servicio/legal, bloqueantes)
1. **Certificado digital tributario** de una entidad de certificación autorizada (para la firma
   digital de cada e-CF).
2. **Enrolamiento como emisor electrónico** en la DGII y **secuencias e-NCF autorizadas** por
   tipo (31 / 32 / 46).
3. Datos fiscales del emisor: **RNC** de SDQ (ya editable en `/admin/pagos`).
4. Definir si a clientes locales se emite 31 (con RNC del cliente) o 32 (consumo) — implica
   **capturar el RNC/cédula del cliente** en el checkout cuando pida crédito fiscal.

## Trabajo de ingeniería (cuando existan las precondiciones)
1. **Numeración e-NCF**: consumir la secuencia autorizada por tipo; controlar vencimiento de
   la secuencia (`FechaVencimientoSecuencia`).
2. **Generación del XML** del e-CF por tipo según el esquema DGII (Encabezado con emisor+
   comprador+totales ITBIS, Detalle de ítems, Totales, Paginación, Fecha/Hora, referencias).
3. **Firma digital** (XAdES) del XML con el certificado.
4. **Envío a los web services de la DGII** (recepción) y manejo del **acuse (ACECF)**:
   aprobado / rechazado / aceptado condicional; guardar **TrackID** y estado.
5. **Representación Impresa (RI)**: PDF con **código de seguridad** + **código QR** (URL de
   consulta DGII) — extender el generador actual `shared/billing/invoice.py`.
6. **Aprobación comercial** (acuse del comprador) y **anulación** de e-NCF cuando aplique.
7. **Contingencia** (emisión offline y reemplazo) y **Notas de Crédito/Débito** electrónicas
   (tipos 33/34) para reembolsos/ajustes.
8. Reporte de estados a la DGII según el calendario de obligatoriedad.

## Enganche en el código
- Un servicio `shared/billing/encf/` (emisor por tipo) que, tras `settle_order` /
  `settle_subscription`, tome la `billing_transaction` en `encf_status='pending'`, genere+firme+
  envíe el e-CF, y actualice `encf_number/status/trackid/security_code/signed_at`.
- Correr async (op agendada) con reintentos y contingencia, sin bloquear el checkout.
