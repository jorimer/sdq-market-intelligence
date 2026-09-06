# El panel de transacciones llega al informe de valuación — plan

## El defecto

`modules/valuation/panel/transacciones.py` computa el panel entero —13 casos verificables, 9
comparables sobre base contable, `resumen()` con mediana/mínimo/máximo, `estado()`,
`contraste_del_modelo()`, `VIAS_ABIERTAS`, `DESCARTADAS`— y el informe NO lo pide: la
metodología y las limitaciones dicen que «el panel dice a cuánto sobre libro se ha pagado»
y no muestran ni tabla, ni rango, ni conteo. El único llamador fuera del panel es
`validation_state()`, que copia el `motivo`.

Familia «servir el dato no alcanza: hay que pedirlo». Cada eje son DOS trabajos: el motor
y la plantilla. Acá faltaba el segundo.

**Y un defecto lateral que apareció leyendo el ensamblador**: `AI_CONTEXT_FILES` está
declarado en `ai_context.py`, pero el ensamblador lo busca en el MÓDULO DEL PRODUCTO
(`modules.valuation.products`), que no lo importa. La huella de contexto de valuación es
solo `ai_context.py`: un arreglo de `narrativa.py` o de `products.py` desplegado a prod NO
invalida la caché de informes (Postgres, sin TTL). Esta sección nueva sería invisible en
todo informe ya generado.

## Qué se hace

1. **Sección nueva `contraste_de_mercado`** (insight + deep dive), después de la
   descomposición y antes de supuestos/limitaciones:
   - si `estado(panel).abierto` es falso: se declara el motivo, sin tabla (el gate se
     consulta antes, no después);
   - tabla de los COMPARABLES (año, comprador, adquirida, país, P/B recomputado, base,
     corte del libro) — solo base contable;
   - mediana / mínimo / máximo / n de `resumen()`, computados;
   - la POSICIÓN del rango P/B de la valuación contra el panel, COMPUTADA (por debajo del
     mínimo, por encima del máximo, solapa; dónde cae la mediana), con la lectura de qué
     supuesto implica — sin usar el panel para producir el valor;
   - los verificables sobre VALOR RAZONABLE (NIIF 3) aparte y marcados, sin entrar al
     resumen: «solo se ordena lo comparable»;
   - el contraste NO valida el modelo (`contraste_del_modelo`): n valuables de n comparables;
   - conteo de descartes y vías abiertas con puntero al anexo.
2. **Anexo `anexo_panel_de_transacciones`** (deep dive): vías abiertas, descartadas con
   motivo, discrepancia RFHL y, por comparable, alcance y caveats — lo que el caso no
   permite afirmar viaja con el número.
3. **Prosa existente**: la metodología y las fuentes apuntan a la sección; fila nueva en la
   tabla de procedencia (relevamiento propio).
4. **Una sola fuente de prosa**: `_secciones_computadas(lec, ...)` la usan `narratives()` y
   `_sample_narrativas_de()`. Hoy son dos diccionarios copiados a mano — la muestra no
   puede desincronizarse de lo real si comparten el constructor.
5. **Huella de caché**: `products.py` expone `AI_CONTEXT_FILES` (el mismo objeto de
   `ai_context.py`) y la lista suma `narrativa.py` y `panel/transacciones.py`.
6. **UI**: etiquetas i18n (es/en/fr) para TODAS las secciones de valuación — hoy ninguna
   tiene y la app muestra «spread roe ke».

## Tests (por la RUTA, contra el código viejo primero)

`modules/valuation/tests/test_el_panel_llega_al_informe.py`:
- `assemble_product_content` (deep dive e insight) trae la sección con la tabla, la
  mediana computada de `resumen()`, los nueve comparables y NINGÚN caso de valor razonable
  en la tabla → hoy falla (la sección no existe).
- la posición del rango se computa: con un `pb` por debajo del mínimo la prosa lo dice, y
  con uno por encima del máximo dice lo contrario (contraejemplo).
- gate cerrado (panel chico) → la sección declara el motivo y no arma tabla.
- el anexo del deep dive lista TODAS las vías y descartes; insight no lo trae.
- HTTP: `GET /api/v1/products/valuation/deep_dive/report` devuelve la sección en
  `narratives` y en `commercial.sections`.
- la muestra sale del MISMO constructor que lo real (monkeypatch del constructor).
- `AI_CONTEXT_FILES` de `products` es el de `ai_context` e incluye los dos archivos; la
  huella del ensamblador cambia al tocar `narrativa.py` → hoy falla.
- títulos: toda sección del manifiesto tiene título en `_SECTION_TITLES` y en los tres
  i18n.

## Cierre — HECHO (2026-09-06)

- [x] 20 tests nuevos en `test_el_panel_llega_al_informe.py`: fallaban contra el código viejo
      (ImportError del símbolo) y pasan contra el nuevo. Más 4 en `test_anchos_de_columna.py`.
- [x] tres gates: pytest 8.702 en verde · ruff limpio · mypy-baseline filter exit 0.
- [x] informe REAL (deep dive e insight) y muestra generados por `assemble_product_report` /
      `assemble_sample_report`, leídos con `pdftotext` y mirados como imagen. Cuatro defectos
      salieron de ahí y no de los tests: «la última fila» de la tabla de fuentes apuntaba a la
      fila nueva; la tabla de 7 columnas partía «Intercommercial» a media palabra (ancho
      igualitario del renderizador compartido); «operación(es)»; códigos de país en prosa.
      Los cuatro corregidos y verificados en un segundo PDF.
- [x] Word (`fmt="docx"`) verificado: la sección y las tablas llegan.
- [x] lessons.md: dos entradas.
