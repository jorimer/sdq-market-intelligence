# T-MP-7 · El producto de proyecciones como eje propio del catálogo

## De dónde salió

Decisión del dueño: la proyección se vende **aparte**, no dentro del eje macro. Medido antes
de construir, un `special:` **no sirve** para eso:

| `special:macro-forecast` | |
|---|---|
| ¿es suscripción? | **no** — `is_subscription_sku` solo admite insight/all_access/enterprise |
| intervalos | **solo `once`** — no admite el cobro anual que se decidió |
| acceso que concede | **ninguno** — `sku_grants` devuelve `[]` |

Un `special:` es, por diseño, una compra puntual cotizada a medida cuya entrega media un
analista (así lo usa `special:research-custom`). Segunda decisión del dueño: **producto propio
en el catálogo**, que gana `insight:<key>` con intervalos mensual/anual y grants reales **sin
tocar `shared/billing`** — que es código de cobro en vivo.

## Las decisiones ya tomadas que esto materializa

* Se vende **aparte** del eje macro.
* **Trimestral es la PUBLICACIÓN; el cobro es anual** con los intervalos que ya existen.
* El suscriptor lo recibe **al emitirse, ~45 días tras cerrar el trimestre** — el rezago del
  IMAE, que es cuando el nowcast tiene algo que decir y ~15 días antes de que el BCRD
  publique el PIB. Eso ya está implementado como el ancla de `macro-forecast-emit`.

## El riesgo conocido, y quién lo vigila

«Un tipo NUEVO se registra en TODAS sus superficies, o DESAPARECE». Al anuario le faltaron
cuatro registros de a uno y **ninguno falló**: cada uno lo hacía desaparecer en un lugar
distinto. No voy a adivinar la lista — voy a crear el eje y **correr los diez tests del
framework que barren el catálogo**, que son los que conocen el contrato completo. Es la
diferencia entre una lista de memoria y una medición.

## Pasos

- [ ] **1.** `CatalogEntry` del eje nuevo en `shared/products/registry.py`.
- [ ] **2.** El producto en `modules/macro_monitor/products_forecast.py` — con su módulo, no
      en `app/`: el eje macro terminó ahí por historia, no por diseño.
- [ ] **3.** Niveles: `pulse` abierto (titular del nowcast) e `insight` por suscripción, que
      es el que da intervalos mensual/anual. Secciones de §5, con **desempeño en el cuerpo**.
- [ ] **4.** `variable_signals()` propio: las proyecciones vigentes del ledger. Acá **sí**
      llevan peso, porque el índice de ESTE eje ES la proyección — y por eso su
      `coverage_projected` sí dice algo, a diferencia del eje macro.
- [ ] **5.** `ESTADO_BACKTEST` de clase, cruzado contra `shared.validation.frescura.MOTORES`:
      un producto no puede reclamar un motor que nadie registró.
- [ ] **6.** Muestra curada de los dos niveles (el framework la exige; un producto listado
      que no se puede mostrar es una vidriera rota).
- [ ] **7.** Correr los tests que barren el catálogo y cerrar lo que señalen, incluidas las
      **DOS listas del frontend**.
- [ ] **8.** Tarifa: **no se hardcodea**. Se publica con `create_tariff` cuando el dueño fije
      el precio; sin tarifa vigente el nivel queda inactivo, que es el comportamiento correcto.

## Sensor
- [ ] Los diez tests del catálogo en verde **sin excepciones declaradas para este eje**.
- [ ] `insight:<key>` admite `annual` y concede grant — comprobado, no supuesto.
- [ ] El eje nuevo **no invade** a los productos en producción (el ruteo de research no lo
      activa en preguntas que no son prospectivas).
