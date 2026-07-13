# Runbook — Rollback de producción (Railway)

Qué hacer cuando un deploy a `main` rompe producción. Objetivo: volver a un estado
sano en minutos, sin improvisar bajo presión.

## Contexto de la arquitectura de deploy

- Railway despliega **automáticamente** en cada push a `main` (integración nativa
  GitHub↔Railway). No hay job de deploy en CI ni gate humano entre CI-verde y prod.
- La imagen se construye con `infrastructure/Dockerfile`. Config de deploy: **solo**
  `railway.toml` en la raíz (el de `infrastructure/` se eliminó por drift).
- El arranque (`infrastructure/start.sh`, rol `web`) corre `alembic upgrade head`
  **antes** de levantar uvicorn. Un deploy incluye, por tanto, las migraciones nuevas.
- Deps fijadas por `requirements.lock` (hashes); build reproducible.

## Decisión rápida: ¿qué falló?

| Síntoma | Causa probable | Ir a |
|---|---|---|
| Health 503 / réplica no arranca / 500s masivos | Código o dependencia del último deploy | **A. Rollback de imagen** |
| El arranque falla en `alembic upgrade` | Migración nueva rota | **B. Rollback con migración** |
| Funciona pero un dato/feature salió mal, sin caída | Regresión lógica no urgente | Revert normal por PR, sin rollback de emergencia |

## A. Rollback de imagen (caso común, sin cambio de esquema)

Cuando el último deploy **no** agregó migraciones (o las agregó pero son aditivas y
compatibles con la versión anterior del código):

1. **Railway → servicio `web` → pestaña Deployments.** Localizar el último deploy
   sano (el previo al que rompió).
2. **Redeploy** de ese deployment (botón "Redeploy" / "Rollback" sobre esa fila).
   Railway reconstruye/republica esa imagen; el `alembic upgrade head` de esa versión
   es idempotente (no re-aplica lo ya aplicado).
3. Verificar: `curl -fsS https://<prod-host>/api/v1/health` → `{"status":"ok"}`; revisar
   logs de arranque (uvicorn running, sin tracebacks).
4. **Bloquear la reintroducción:** revertir el commit culpable en `main`
   (`git revert <sha>`) para que el auto-deploy no vuelva a publicar la versión rota.

## B. Rollback cuando la migración nueva es el problema

Las migraciones tienen `downgrade()` real (verificado: 50/51; el CI
`migrations-reversible` prueba el round-trip de la última en cada PR). Aun así, un
downgrade en prod es delicado — **preferir siempre A si la migración nueva es aditiva**
(columna/tabla nueva que el código viejo simplemente ignora). Bajar el esquema solo si
la migración nueva es incompatible con el código anterior.

1. **Poner el servicio en pausa** o escalar a 0 réplicas mientras se opera (evita que
   una réplica sirva contra un esquema en transición).
2. **Downgrade manual** contra la DB de producción, un paso:
   ```
   alembic -c infrastructure/alembic.ini downgrade -1
   ```
   (Ejecutar desde una réplica/one-off con `DATABASE_URL` de prod. NO saltar varios
   pasos a ciegas: bajar de a uno y verificar.)
3. **Rollback de imagen** a la versión previa (pasos A.1–A.2).
4. Revertir el commit en `main` (A.4) y verificar health.

⚠️ Si la migración rota **ya borró o transformó datos** y su `downgrade` no los
restaura, el rollback de esquema no alcanza: restaurar desde el backup de Postgres de
Railway (snapshot previo al deploy). Por eso la regla de abajo.

## Regla permanente: migraciones aditivas primero

Para que A sea siempre viable, separar cambios de esquema destructivos de los
despliegues de código:

- **Deploy N:** migración **aditiva** (agregar columna/tabla, backfill, código que
  escribe en ambos lados). Nunca borra ni renombra en el mismo deploy que estrena el
  código que lo necesita.
- **Deploy N+1** (tras confirmar N sano): migración **destructiva** (drop de la columna
  vieja), cuando ya nada la lee.

Así un rollback del código nunca choca contra un esquema que le quitó algo.

## Ensayo pendiente (gate de go-live)

Este runbook está **verificado en dev** (build reproducible + boot + migraciones +
round-trip del downgrade). El **ensayo en producción** (deploy → rollback → verificación
en una ventana controlada) requiere autorización del dueño y una ventana de
mantenimiento; queda como paso previo al go-live, no ejecutado aún.
