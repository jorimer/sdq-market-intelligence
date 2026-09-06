# La pasada de FORMA del informe

Tres defectos, los tres medidos sobre el PDF y no deducidos del código.

## A · La portada rotula «Período» sobre un corte de información

`render.py:332` imprime `**Período:** {period}` con lo que el producto declare en
`available_periods()`.

**Medido contra producción, los 18 ejes del catálogo.** Cuatro pasan una fecha completa:

```
banking          → 2026-06-30     cierre de trimestre
macro            → 2025-12-31     cierre de año
monetary_policy  → 2026-07-31     cierre de mes
macro_forecast   → 2026-09-06     ← NO es un cierre: es el corte de información
```

Los tres primeros **se leen bien**: una fecha de cierre bajo «Período» es una forma legítima
de nombrar el período. El único mal rotulado es el de proyecciones, y su propio
`std_methodology` ya lo llama por su nombre: *«Corte del informe: 2026-09-06»*.

Corrijo mi encuadre anterior: dije «la portada dice Período sobre una fecha» como si fuera
general. Es de un eje.

## B · El informe cita una serie por la ruta de la hoja de cálculo

La tabla de trayectoria publica el `serie` crudo:

```
| bcrd.xls.pib_2018.serie_original_indice | 2026-Q3 | 5.57% | … |
```

El mecanismo para esto **ya existe y la doctrina ya está escrita**, en el comentario de
`canonical.CURATED_LABELS`:

> *«Todo lo demás que sale del motor de Excel es extracción masiva —dato real, pero con el
> nombre que la planilla dejó—, y se declara como no-curado **para que un informe no lo cite
> por la ruta de la hoja de cálculo**.»*

`is_curated("bcrd.xls.pib_2018.serie_original_indice")` da **False**, y el informe lo cita
igual. Nada lo vigila.

Ojo: esto EMPEORÓ con el arreglo del ledger. Antes la fila decía `pib_real` —feo pero
corto—; ahora dice el código completo, que es lo correcto para el ledger y lo peor posible
para un informe que se vende.

## C · Los subíndices salen como cajas negras

**Medido**, renderizando cada familia y leyendo el PDF:

```
subíndices    ₀₁₂₃₄₅₆₇₈₉ₜ  →  ■■■■■■■■■■■     TODOS fallan
superíndices  ⁰¹²³⁴⁵⁶⁷⁸⁹   →  ■¹²³■■■■■■      solo ¹²³ (que son Latin-1)
griego        αβγδλμσωΣΔΩ  →  αβγδλµσωΣ∆Ω     bien
matemática    ± × ÷ ≈ ≤ ≥ ≠ ∑ √ ∞ ·          bien
flechas       → ← ↑ ↓ ⇒                       bien
tipografía    — – … « » “ ” ¡ ¿ § † € $       bien
```

**Corrijo lo que venía diciendo**: la `λ` renderiza perfecto. Lo que falla son los subíndices
y los superíndices distintos de ¹²³. `BV₀` y `λ₁` salían mal por el subíndice, no por la
letra griega.

**Y esto NO necesita decisión del dueño.** Yo había planteado «transliterar o cambiar la
fuente», y hay una tercera que es mejor que las dos: ReportLab entiende marcado `<sub>` y
`<super>`, y con la fuente que ya tenemos dibuja un subíndice de verdad. Verificado en PDF y
mirando la imagen renderizada:

```
Con marcado: BV₀  λ₁  x⁴   → subíndice y superíndice reales
Sin marcado: BV■  λ■  x■   → cajas negras
```

Ni transliteración (que pierde la forma) ni fuente nueva (que cambia el aspecto de TODOS los
informes).

---

## Plan

1. **`period_label`** en los dos renderers, con default «Período». Solo `macro_forecast` lo
   pisa con «Corte», que es como su propia metodología ya lo llama.
2. **Etiqueta curada** para la serie del PIB, y que el informe use `curated_label()`. Más un
   guard: ninguna prosa de informe puede imprimir un código `bcrd.xls.` crudo.
3. **Sub/superíndices → marcado** en el PDF; en el Word, formato de run (`font.subscript`),
   que es lo que Word entiende. La REGLA en una constante compartida, como el espacio duro.

## Verificación
- [ ] Los tests contra el código VIEJO tienen que FALLAR
- [ ] Leer el PDF: ningún `■`, ningún `bcrd.xls.` en la prosa
- [ ] Mirar la imagen renderizada, no solo el texto extraído
- [ ] Los tres gates
