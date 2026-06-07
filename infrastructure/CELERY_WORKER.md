# Worker de tareas (Celery) — jobs en background robustos

Los jobs largos (backfill del SIB; a futuro: sync de BCRD/ONE/Comtrade) corren en
un **worker Celery separado** del proceso web, usando **Redis** como broker. Así un
redeploy del web no los mata, y si el worker se cae el broker re-encola la tarea
(que es **idempotente e incremental**, por lo que reanuda).

## Activar (Railway)

1. **Redis**: ya existe el servicio Redis; toma su `REDIS_URL` (privada).
2. En el servicio web, variables de entorno:
   - `REDIS_URL = <url de Redis>`
   - `USE_CELERY = true`
3. **Crear un segundo servicio** en Railway desde el mismo repo (Deploy from repo),
   con **Start Command**:
   ```
   celery -A shared.tasks.celery_app worker --loglevel=info --concurrency=1
   ```
   y las mismas variables de entorno que el web (`DATABASE_URL`, `REDIS_URL`,
   `SETTINGS_SECRET`, etc.). Usa la misma imagen Docker.

Sin estos pasos (o con `USE_CELERY` apagado), el backfill corre en un hilo dentro
del web — funciona, pero un redeploy lo reinicia (la escritura incremental hace
que reanude sin perder lo ya guardado).

## Local
```
celery -A shared.tasks.celery_app worker --loglevel=info
```
(requiere un Redis local y `REDIS_URL`/`USE_CELERY` en `.env`)
