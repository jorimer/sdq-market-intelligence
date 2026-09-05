# Que la medida viaje con la proyección, y desplegar — plan

Dos trabajos, en este orden: primero el código, después UN despliegue con las dos cosas.

---

## 1 · La medida se pierde al salir del ledger

`ForecastLog.measure` ya existe (commit `7e9f7328`), pero **muere en la puerta del ledger**.
`procedencia.meta_de` no la copia y `ProjectionMeta` no tiene dónde ponerla, así que todo lo
que lee una proyección vuelve a adivinar la unidad. Es el mismo defecto que acabo de cerrar,
un salto más adelante en la cadena.

### Lo que está publicando hoy

Medido leyendo cada superficie, no supuesto:

| dónde | qué publica | por qué está mal |
|---|---|---|
| `app/products_macro.variable_signals` | `«bcrd.xls.pib_2018.serie_original_indice · proyección 2026-Q3» = 0,38` | el valor es una TASA y la etiqueta nombra una serie que es un ÍNDICE (~133) |
| `shared/registry/provenance.projection_sentence` | «…con intervalo de 80 % entre 3.1 y 4.7» | dos números sin unidad, y el punto ni aparece |
| `products_forecast._md_trayectoria` | `f"{d['punto']:.2f} %"` | el «%» está **hardcodeado**: acierta por casualidad, es la misma suposición |
| `products_forecast._md_escenarios` | ídem | ídem |
| `_SAMPLE_PAYLOAD` (muestra curada) | `"serie": "pib_real"` | la vidriera del producto enseña el identificador ROTO |

### Dónde tiene que vivir el vocabulario

**En `shared/`, no en el módulo.** La prosa (`shared/registry/provenance.py`) y el gate
(`shared/registry/projection.py`) tienen que interpretarlo, y `shared/` no puede importar de
un módulo sin invertir la dependencia que el repo declara. Se mueve
`modules/macro_monitor/forecasting/medida.py` → `shared/data/medida_de_pronostico.py`, al
lado de `series_nature.py`, que es el mismo concepto un nivel más arriba (la naturaleza de la
SERIE) y ya justificó vivir ahí.

Sin alias de compatibilidad en la ubicación vieja: dos nombres para una cosa es cómo
empiezan las dos definiciones que se contradicen.

### El arreglo

1. **Mover el módulo** y actualizar los cinco importadores.
2. **`ProjectionMeta.measure`, REQUERIDO**, justo después de `point` — es lo que califica a
   ese número. Sin default, por la misma razón que en `ledger.registrar`: un default
   reintroduce la suposición. Rompe los constructores de los tests, y eso es la presión
   correcta.
3. **El gate lo exige.** Igual que `n_oos_overlapping is None` es rechazo porque «el
   solapamiento se declara, no se supone», una proyección cuya unidad no se declaró no puede
   anclar una afirmación. Rechaza también un valor fuera del vocabulario.
4. **`procedencia.meta_de` la copia** de `fila.measure`.
5. **Las cinco superficies**, todas, o el documento se contradice según por dónde salga:
   la prosa compartida, la etiqueta del registro, las dos tablas del producto (que dejan de
   hardcodear «%») y el titular. Y la muestra curada deja de enseñar `pib_real`.

### Tests, contra el código viejo primero

- La etiqueta del registro y la frase de procedencia NOMBRAN la unidad (fallan hoy).
- El gate rechaza una proyección sin medida y una con medida inventada (falla hoy: admite).
- **Paridad de unidad**: ninguna superficie escribe `%` por su cuenta — se computa de la
  medida. Estructural, con `getsource`, porque es un literal y un literal vuelve.
- El `_SAMPLE_PAYLOAD` declara la medida y una serie que EXISTE, verificado contra el mismo
  código que resuelve la del bloque.

---

## 2 · Desplegar y verificar en prod

Va DESPUÉS del punto 1: dos despliegues para el mismo arreglo es un despliegue de más, y
cada uno dispara ~30 syncs.

1. `git push -u origin claude/heuristic-payne-083d13` + `gh pr create --base main`.
2. Esperar los TRES checks (`backend-test`, `frontend-build`, `docker-build`) y
   `gh pr merge <n> --merge`. Si falla con «3 of 3 required status checks are expected»
   estando en verde, la rama quedó atrás de main → actualizar y reintentar.
3. **Comprobar QUÉ COMMIT sirve antes de verificar nada**, y por CONTENENCIA, no por
   igualdad — otra sesión puede mergear en paralelo y ganar el deploy:
   ```
   c=$(curl -s $PROD/api/v1/health | jq -r .deployment.commit)
   git merge-base --is-ancestor <mi-sha> "$c"
   ```
   Tres estados, no dos: clave `deployment` ausente = código viejo; presente con `null` =
   nuevo sin sello; con SHA = cotejable.
4. La migración `d1e6f3a9c7b2` corre en el arranque del contenedor y aplica el backfill.
   **Ojo**: un deploy atascado YA migró la base aunque no sirva tráfico.
5. Verificar el CAMBIO DE ESTADO, no la ausencia de error. Línea base de HOY, tomada antes
   de tocar nada, en `GET /api/v1/products/readiness` → `macro_forecast` → `pulse` → `g1`:
   **«1 proyección(es) vigente(s); 0 conjunto(s) con backtest puntuado»**. Después del
   despliegue, la fila del BVAR tiene que dejar de ser huérfana: se comprueba pidiendo la
   serie a la que apunta y viendo que existe.
6. Correr `macro-canonical-sync` (que encadena la puntuación) y leer `forecasts_scored`.
   **No va a subir de 0 hasta que el BCRD publique 2026-Q3** —el trimestre cierra el 30 de
   septiembre y el PIB tiene 60 días de rezago—, así que lo que se verifica hoy es que las
   filas dejaron de ser IMPUNTUABLES, no que se puntuaron. Decirlo así y no confundir las dos.

## Los tres gates

`pytest modules/ shared/ -q` · `ruff check modules/ shared/ app/` ·
`mypy shared/ modules/ app/ --no-incremental | mypy-baseline filter` (exit code del FILTRO).
