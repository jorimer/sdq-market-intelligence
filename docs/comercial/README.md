# Material comercial — dossier de producto y marca

Paquete de **handoff para diseño**: todo lo que un diseñador senior necesita para construir
la presentación comercial de SDQ·MIP sin volver a preguntar, y sin inventar nada que el
código no sostenga.

| Archivo | Qué es |
|---|---|
| `SDQMIP_Dossier_Comercial_y_Marca.docx` | El dossier, editable. 31 páginas. |
| `SDQMIP_Dossier_Comercial_y_Marca.pdf` | El mismo, para leer y circular. |
| `assets/` | Logotipo, bloques de marca, diagramas, muestras de componentes, tokens. |

## Cómo se regenera

**No se edita a mano.** El catálogo de productos y el tarifario se leen del código
(`shared/products/registry.py`, `shared/billing/skus.py`), así que un producto nuevo entra
al documento con solo regenerarlo:

```bash
pip install python-docx
python scripts/build_dossier_comercial.py            # → docs/comercial/*.docx
soffice --headless --convert-to pdf --outdir docs/comercial \
        docs/comercial/SDQMIP_Dossier_Comercial_y_Marca.docx
```

El script valida contra el esquema OOXML; si el DOCX no abre en LibreOffice, es que el
orden de algún elemento se rompió (ver el comentario sobre `_insert_ordered`).

## Las tres reglas que el documento respeta (y hay que seguir respetando)

1. **Ninguna cifra de validación está escrita a mano.** No hay Ginis, ni IC, ni N. El
   documento declara de dónde se leen (`GET /api/v1/products/credenciales`) y por qué una
   cifra copiada se desincroniza. Ver `docs/CLAIMS_COMERCIALES.md`.
2. **El catálogo se lee del código**, nunca de una lista paralela que envejece.
3. **Los precios son PROPUESTA** hasta que el dueño los publique en `/admin/tarifario`.

## Assets

| Archivo | Qué es |
|---|---|
| `arco.svg` | Símbolo Arco, variante recomendada, vectorial. |
| `logo_arco_v2_1024.png` | La misma, rasterizada a 1024 px con fondo transparente. |
| `logo_arco_favicon_1024.png` | El símbolo tal como se sirve hoy como favicon de la app. |
| `logo_produccion_256.png` | El símbolo tal como va en los informes PDF y Word. |
| `logo_variants.png` | Las tres variantes comparadas (figura 2 del dossier). |
| `lockup_light.png` · `lockup_dark.png` | Bloque de marca en claro y en oscuro. |
| `arch.png` | Diagrama de arquitectura de producto (figura 1). |
| `ui_light.png` · `ui_dark.png` | Muestra de componentes en ambos temas (figura 4). |
| `tokens.css` | Copia literal de los tokens de `frontend/src/index.css`. |

## Lo que el dossier deja abierto

Decisiones del dueño, no del diseñador (§8.5 del documento):

- Geometría y color únicos del símbolo Arco — hoy circulan tres variantes.
- Unificar la paleta de informes (`navy #1A365D` + `signal red #E11D48`) con la de la
  aplicación (`#0A1A3A` + `#1E6FFF`).
- Cerrar el tarifario y encender la pasarela de pago.
