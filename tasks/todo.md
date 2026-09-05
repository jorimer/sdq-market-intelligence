# La frase de cobertura dice algo falso, y se contradice cuatro líneas después

## Lo que el informe publica hoy

`SDQ_Proyecciones_Deep-Dive_Sistema_2026-09-05.pdf`, §8 Metodología y fuentes, con cuatro
líneas de distancia entre las dos:

> **Cobertura:** 100% del índice se construye sobre dato real medido en la fuente.

> **Procedencia por variable:** 0% del peso de este índice se sostiene en dato real con
> fuente citable; … `pib_real · 2026-Q3` no tiene dato en este período y se reporta como
> brecha, no como cero.

Las dos se COMPUTAN, de dos sitios distintos, y se contradicen. En un informe de PRONÓSTICO
la primera además es falsa por construcción: el docstring del propio producto lo dice —*«acá
el índice del eje **ES** la proyección»*—. Una proyección no es «dato real medido en la
fuente».

## Dos defectos, no uno

### A · El producto contesta otra pregunta

`products_forecast.data_signals()`:

```python
coverage=1.0 if vig else 0.0
```

Eso responde *«¿hay alguna proyección vigente?»*. Pero `DataHealth.coverage` declara en su
contrato (`contract.py:42-54`) responder otra: *«¿qué fracción del PESO de mi índice está
anclada a dato real?»* — y lo declara con `coverage_kind = "fraccion_real_del_indice"`.

Estado real medido en producción: **una** proyección vigente, `pib_real · 2026-Q3`, que **no
pasa el gate** de admisibilidad (la tabla del informe la publica con «¿ancla una afirmación?
**no**»), más **una** cifra determinada (2026-Q2, identidad aritmética sobre IMAE publicado —
ésa sí es dato real). Y aun así `g1 = 1.00`, `cobertura=1.00`.

### B · La frase de metodología IGNORA `coverage_kind` — y ya hay otro eje publicando falso

El mecanismo para esto ya existe y ya se usó: `provenance.coverage_sentence()` elige entre
`FRASE_COBERTURA_INDICE` y `FRASE_COBERTURA_INSTRUMENTO` según `coverage_kind`. Su comentario
dice por qué:

> *«la frase de índice afirmaba "del peso de este índice" para todos los ejes, y en el de
> evaluación de leyes eso es sencillamente falso … La frase salía en la Metodología del
> informe y en el payload de calidad de la API paga.»*

**El arreglo se hizo en `provenance.py` y NO en `report_sections._methodology_md`**, que
sigue con la frase de índice cableada. Verificado ejecutando las dos:

```
EJE DE LEYES (coverage_kind = instrumento)
  → **Cobertura:** 47% del índice se construye sobre dato real medido en la fuente.
EJE DE PROYECCIONES
  → **Cobertura:** 100% del índice se construye sobre dato real medido en la fuente.
```

O sea que el eje de leyes publica HOY, en la metodología de su informe, exactamente la frase
que el repositorio ya declaró falsa para él. Familia «un guard existe en un motor y falta en
el otro».

---

## Plan

### 1 · Una tercera semántica de cobertura: `COVERAGE_PROJECTION`

Ni «fracción real del índice» ni «metas del instrumento». La pregunta de este eje es *«¿qué
fracción de lo que publico está sostenida por un pronóstico ADMISIBLE o por una cifra
determinada?»*, que es la que su propio `variable_signals` ya computa.

### 2 · `_methodology_md` rutea por `coverage_kind`, y las frases viven en UN solo mapa

Las dos superficies —metodología y procedencia— toman su frase del mismo mapa
`coverage_kind → frase`. No pueden volver a divergir porque no hay dos listas.

Las redacciones siguen siendo distintas a propósito: la de metodología es la *afirmación de
método* (decisión del dueño del 2026-08-31: sin el inventario de faltantes, que desvaloriza),
la de procedencia es la completa. Lo que se unifica es el RUTEO, no el texto.

### 3 · El guard: ningún `coverage_kind` puede caer al default en silencio

Test estructural: todo valor del vocabulario tiene frase en las DOS superficies. Agregar un
cuarto `coverage_kind` sin su frase falla, en vez de heredar la de índice.

### 4 · El número

`coverage` del eje de proyecciones pasa a medir lo que su frase afirma.

**Consecuencia que hay que MEDIR y declarar, no esconder:** hoy `g1 = 1.00` y el eje publica
con readiness 0,85. Con el número honesto g1 baja. Si eso lo saca del umbral de publicación,
es una decisión del dueño y se le dice — pero la salida no puede ser dejar publicada una
frase falsa para sostener un gate.

## Verificación
- [ ] Correr los tests nuevos contra el código VIEJO y ver que FALLAN
- [ ] Medir el readiness ANTES y DESPUÉS, por nivel
- [ ] Comprobar que el eje de LEYES deja de publicar la frase de índice
- [ ] Los tres gates
