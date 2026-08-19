# Triaje de validación — los 16 ejes del catálogo

**Fecha:** 2026-08-19 · **Fase 4** del [plan de cierre](PLAN_CIERRE_BRECHAS_VALIDACION.md)
**Declarado en el código:** `ESTADO_BACKTEST` en la clase de producto de cada eje, publicado
en el payload de readiness (`detail.backtest`) y exigido por
[`shared/products/tests/test_estado_de_validacion.py`](../shared/products/tests/test_estado_de_validacion.py).

---

## 0. El criterio, y lo que reveló

El plan pedía un criterio único: **¿existe un desenlace realizado, observable e independiente
del índice?** Aplicándolo apareció una pregunta anterior que ninguno de los documentos hacía:

> **¿Hay algo que ordenar?**

Un backtest de discriminación —Gini, IC de rango— mide si un score **ordena** sujetos por su
desenlace futuro. Banca ordena entidades; seguros, aseguradoras; IRMP y comercio, países;
sectorial, ramas; social, regiones. Los cinco ejes sectoriales nacionales —turismo, zonas
francas, energía, construcción, telecom— producen **un score por año para el país entero**.
Un solo sujeto. No hay nada que rankear, y ninguna cantidad de trabajo de datos lo arregla
mientras el índice sea nacional.

**Eso reclasifica la brecha.** «Estos ejes no están validados» sugería una tarea pendiente de
esfuerzo; lo que hay es una **imposibilidad de diseño con una salida nombrada**: darles corte
transversal (provincia, parque, distribuidora) o aceptar que su credencial no es predictiva.

Y hay una segunda trampa, que el eje sectorial ya nos cobró: en los cinco, **las dimensiones
del índice se computan de las mismas series que serían el desenlace**. El ITT se arma de las
llegadas; validarlo contra llegadas futuras mide persistencia de la serie, no anticipación —
el mismo defecto que en banca hace que `eficiencia` "prediga" el ROA futuro con Gini +0,71.

---

## 1. El triaje

| Eje | Motor | Obstáculo | Qué haría falta |
|---|---|---|---|
| `banking` | **sí** | — | — |
| `macro` (IRMP) | **sí** | — | — |
| `trade` | **sí** | — | — |
| `esg` | **sí** | — | — |
| `social_dev` | **sí** | — | — |
| `pension` | **sí** | — | — |
| `insurance` | **sí** | — | — |
| `agribusiness` (IAI) | **sí** | — | corrido contra dos desenlaces; sin poder sobre el tamaño |
| `tourism` | no | `sin_corte_transversal` | llegadas y ocupación **por provincia o polo turístico** |
| `free_zones` | no | `sin_corte_transversal` | panel **por parque** o por sector de zona franca |
| `energy` | no | `sin_corte_transversal` | serie **por distribuidora o circuito** (EDEs) |
| `construction` | no | `sin_corte_transversal` | **ejecución** de permisos (MIVHED publica emisión) + corte provincial con historia |
| `telecom` | no | `dato_pendiente` | el boletín INDOTEL está **congelado en 2022-Q1**; ITU da nivel nacional, no corte |
| `monetary_policy` | no | `autoreferencial` | tiene backtest, pero de **clasificación**, no de discriminación transversal |
| `economic_structure` | no | `autoreferencial` | no hay índice que validar: es una vista descriptiva; su verificación es contable |
| `law` | no | `autoreferencial` | el desenlace es el cumplimiento que el propio eje mide |

**Nueve con motor · siete sin motor, los siete con obstáculo declarado y explicado.**

---

## 2. Los tres destinos, resueltos

**a) Validable ahora → ninguno de los siete.** No por falta de trabajo: por falta de sujetos
que ordenar. Forzarles un Gate E produciría un número sin contenido, que es peor que la
ausencia — y es exactamente el error que el eje sectorial cometió validando un índice de
inversión contra el empleo.

**b) Validable cuando llegue el dato → cinco, con el dato nombrado.** Turismo, zonas francas,
energía y construcción necesitan **desagregación** (provincia · parque · distribuidora ·
ejecución de permisos). Telecom necesita que **vuelva su fuente**. Ninguna de las cinco es una
promesa vaga: cada una nombra qué pedir y a quién.

**c) No validable por naturaleza → tres.** `law` (el desenlace es lo que mide),
`economic_structure` (no hay índice, hay una identidad contable) y `monetary_policy`, que es
un caso aparte: **sí tiene backtest** —expanding-window out-of-sample, point-in-time, 190
decisiones del BCRD— pero es un problema de **clasificación de una serie**, no de
discriminación entre sujetos. Se lee por macro-F1 y por el recall de las clases que el
baseline nunca ve, y empata al baseline ingenuo en accuracy. Meterlo en la misma tabla que un
Gini sería comparar dos cosas distintas.

---

## 3. Lo que impide que esto envejezca

`ESTADO_BACKTEST` declara hechos de **diseño**, no el veredicto de la última corrida. Si un
eje concluye o no lo dice su reporte, que se recalcula y se marca obsoleto solo (Fase 1).
Poner «concluyente» en esta declaración la congelaría — el defecto exacto que abrió el plan.

El test estructural exige, y tiene dientes verificados:

1. Los 16 ejes declaran. Quitar una declaración pone el test en rojo.
2. **El que dice tener motor lo tiene registrado de verdad**: se cruza contra
   `shared.validation.frescura.MOTORES`. Un producto no puede reclamar una validación que
   nadie registró — cambiar el nombre del motor a uno inventado pone el test en rojo.
3. El que no lo tiene declara un obstáculo de una lista **cerrada** y lo explica en más de
   doce palabras: «pendiente» no es un obstáculo y un rótulo no se puede discutir.
4. Si el obstáculo es `dato_pendiente`, nombra el dato. Una brecha sin nombre no se puede
   cerrar ni presupuestar.
5. Los seis sin motor están fijados por nombre: si alguno gana uno, el test falla y obliga a
   actualizar este triaje en vez de dejar la lista vieja conviviendo con la realidad nueva.

---

## 4. Qué se puede vender de cada grupo

- **Con motor (8 ejes + banca):** la cifra de su reporte, con su IC, su N y su marca de
  frescura. Nada de esto es «grado Basilea» y todos lo declaran.
- **Sin corte transversal (4):** índices **descriptivos** de dato real, con su cobertura y su
  procedencia. Se venden por lo que miden hoy, no por lo que anticipan.
- **Dato pendiente (telecom):** honesto por diseño mientras la fuente no vuelva — y ahora
  dice desde cuándo está congelado.
- **Autoreferenciales (3):** su verificación es de otra clase (contable, de bindings, de
  clasificación) y cada uno la nombra.
