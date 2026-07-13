# Checklist para habilitar la facturación electrónica (e-CF) de SDQ

Pasos que dependen del dueño para desbloquear la emisión real de e-CF. En orden. La parte
técnica (firma, envío, QR) la retoma Claude en cuanto tengas el **certificado** + el acceso a
**TesteCF**.

---

## Paso 1 — Requisitos previos en la DGII (probablemente ya los tenés)
- [ ] **RNC de SDQ** activo y **al día** con las obligaciones tributarias.
- [ ] Acceso a la **Oficina Virtual (OFV)** de la DGII con su **dispositivo de seguridad**
      (token o tarjeta de códigos).
- [ ] Estar **autorizado a emitir Comprobantes Fiscales (NCF)**.

## Paso 2 — Conseguir el Certificado Digital *para Procesos Tributarios* (lo más importante)
Es el archivo que **firma** cada factura electrónica. Sin él no se puede emitir.
- [ ] Solicitarlo a una **entidad de certificación autorizada por el INDOTEL** (Ley 126-02).
      *Verificá la lista vigente en indotel.gob.do / dgii.gov.do antes de contratar.*
- [ ] Debe ser del tipo **"para Procesos Tributarios"**, emitido a nombre de la **persona que
      representará a SDQ** ante la DGII (representante legal o autorizado).
- [ ] Te entregan un archivo **`.p12` (o `.pfx`)** + una **contraseña**. Guardalos seguros.
      *(Claude los carga encriptados en `/admin/pagos`; nunca los mandes por chat/correo sin
      cifrar.)*
- [ ] Anotá la **fecha de vencimiento** del certificado (hay que renovarlo).

## Paso 3 — Solicitar ser Emisor Electrónico (DGII)
- [ ] Completar y enviar el **Formulario FI-GDF-016** ("Solicitud para ser Emisor
      Electrónico, Vers. C") por la Oficina Virtual.
- [ ] Recibir en el **buzón de la OFV** el **usuario y clave del portal de Facturación
      Electrónica** (incluye acceso al ambiente de pruebas **TesteCF**).

## Paso 4 — Certificación técnica (acá vuelve a entrar Claude)
- [ ] Pasarme: el **certificado `.p12` + contraseña**, y las **credenciales/URL de TesteCF**.
- [ ] Con eso, Claude corre los **Sets de Pruebas** de la DGII (Datos · Simulación ·
      Comunicación) desde el software de SDQ y prepara la **Declaración Jurada**.

## Paso 5 — Autorización y secuencias e-NCF
- [ ] Tras aprobar los sets, la DGII **autoriza a SDQ como Emisor Electrónico**.
- [ ] Solicitar en la OFV las **secuencias de e-NCF** por tipo:
      **31** (Crédito Fiscal), **32** (Consumo), **46** (Exportación).
- [ ] Cargar esos **rangos** en `/admin/pagos` (tarjeta "Secuencias e-NCF") — ya está listo.
- [ ] Cargar el **RNC y datos del emisor** en `/admin/pagos` (tarjeta "Emisor de la factura").

---

## Qué necesita Claude de vos para construir la firma + el envío (Slices 4–7)
1. El **certificado `.p12`/`.pfx` + su contraseña** (se cargan encriptados; no los expongas).
2. Las **credenciales y URLs del ambiente de pruebas TesteCF** (y luego las de producción).
3. Los **rangos de e-NCF** autorizados por tipo.
4. **RNC + razón social + dirección** de SDQ como emisor.

## Decisión pendiente (menor, técnica)
- **Tipo de cambio DOP/USD** para el e-CF: SDQ factura en USD pero el e-CF usa DOP como base.
  Propuesta de Claude: usar la **tasa del BCRD** que la plataforma ya ingiere, congelada al
  momento de emitir. (Se confirma al construir el envío.)

## Contacto útil
- DGII — Facturación Electrónica: **(809) 689-3444** · información en **dgii.gov.do**.
