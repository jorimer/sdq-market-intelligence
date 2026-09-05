# La estructura del informe de proyecciones

## Lo que publica hoy, medido sobre el PDF del 2026-09-05

Nueve secciones numeradas, más dos tablas de portada:

```
(portada) Proyecciones vigentes                    ← tabla, SIN encabezado
(portada) Incidencia sectorial proyectada · 2026-Q3 ← tabla, SIN encabezado, 18 filas
1. Nowcast del trimestre en curso
2. Trayectoria proyectada          ← vuelve a publicar la 1ª tabla, CON encabezado
3. Escenarios a 3-8 trimestres (sin track record)
4. Lectura sectorial               ← vuelve a publicar la 2ª tabla, CON encabezado
5. Desempeño de nuestras proyecciones anteriores
6. Metodología y límites           ← del producto
7. Glosario
8. Metodología y fuentes           ← del framework; lista las fuentes inline
9. Fuentes y referencias           ← del framework; LAS MISMAS fuentes, en viñetas
```

### A · Las tablas de portada son duplicados EMPEOBRECIDOS

`render()` arma `tables` con las mismas filas que la prosa de §2 y §4 ya renderiza en
Markdown, y las de portada **pierden el encabezado**: la lista por comprensión emite solo
filas de dato. Después del arreglo de la lectura sectorial la de portada es además un
SUBCONJUNTO — 4 columnas contra 5, sin la de «proyectado».

Y el dueño ya decidió sobre este patrón, para otro producto. El docstring de
`render_product_pdf` lo tiene escrito:

> *«`tables_last` mueve el bloque de tablas DESPUÉS de las secciones narrativas: un informe
> que abre con páginas de tablas antes de una sola frase se lee como un anexo, no como un
> informe (pedido del dueño sobre el de brand_intel). Opt-in por producto.»*

Este informe abre con dos páginas de tablas antes de una sola frase. Pero acá `tables_last`
no es la cura: **la cura es no publicarlas dos veces.**

*(Corrijo una lectura mía anterior: el encabezado que se repite dentro de §4 NO es una tabla
duplicada, es el encabezado que se repite al saltar de página. La duplicación real es
portada ↔ sección.)*

### B · Hay una trayectoria de SIETE puntos y no se dibuja ningún gráfico

```python
items = [(d["horizonte"], d["punto"]) for d in proys]
if len(items) >= 2:
    graficos.append({...})
```

`proys` son las proyecciones VIGENTES: hoy hay **una**, así que no se dibuja nada. Pero el
informe publica además **seis escenarios** (2026-Q4 → 2028-Q1) que son puntos de la misma
trayectoria y viven en §3. Siete puntos disponibles, cero dibujados.

Al graficarlos hay que conservar la distinción que §3 existe para sostener: un escenario no
es un pronóstico. Van en la misma serie con marca distinta, nunca fundidos.

### C · Dos secciones se llaman «Metodología» y las fuentes salen dos veces

- §6 «Metodología y límites» es del PRODUCTO y es contenido real: cómo funcionan el nowcast,
  el BVAR y la desagregación sectorial. Se queda.
- §8 «Metodología y fuentes» es del FRAMEWORK: corte, frescura, cobertura, validación,
  procedencia. También se queda.
- Los dos títulos empiezan igual, y §8 lista las fuentes inline mientras §9 las repite en
  viñetas — las mismas dos, a cuatro líneas.

Lo local: renombrar la del producto por lo que de verdad es. Lo compartido —que §8 y §9
publiquen la misma lista— toca a TODOS los productos y va aparte, medido, no de arrastre.

### D · Falta lo que el dueño pidió como estándar

El estándar de nueve secciones (portada, resumen ejecutivo, propósito y alcance,
antecedentes, análisis, metodología, conclusión de valor, supuestos y limitaciones, anexos)
se aplicó al eje de VALUACIÓN y este eje nunca lo recibió. Le faltan **resumen ejecutivo** y
**propósito y alcance**, que son las dos que un lector usa para decidir si sigue leyendo.

---

## Plan

1. **Sacar las tablas duplicadas de la portada.** La prosa ya las publica, con encabezado y
   con más columnas. Deja el titular y el gráfico.
2. **Dibujar la trayectoria completa**: vigentes + escenarios, con los escenarios marcados
   como lo que son.
3. **Renombrar §6** para que dos secciones no digan «Metodología».
4. **Resumen ejecutivo y propósito y alcance**, computados de la misma prosa que el resto —
   nunca escritos a mano, nunca desde la muestra.
5. Declarar §8↔§9 como deuda COMPARTIDA, con la cuenta de cuántos productos afecta.

## Verificación
- [ ] Los tests nuevos, contra el código VIEJO, tienen que FALLAR
- [ ] Contar las tablas del PDF antes y después
- [ ] Comprobar que el gráfico sale con UNA sola proyección vigente
- [ ] Los tres gates
