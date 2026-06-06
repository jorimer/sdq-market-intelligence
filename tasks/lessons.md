# Lecciones aprendidas

> Bitácora de patrones de error y reglas para no repetirlos.
> Revisar al inicio de cada sesión. Agregar entrada después de cualquier corrección del usuario.

## Formato

Cada entrada sigue esta estructura:

```
### YYYY-MM-DD — <título corto>

- **Síntoma**: qué se observó (tests rojos, comportamiento incorrecto, comentario del usuario).
- **Causa raíz**: por qué pasó realmente (no el síntoma).
- **Regla**: qué hacer distinto la próxima vez. Concreta y verificable.
- **Disparador**: cuándo aplica esta regla (contexto en que se debe recordar).
```

---

## Entradas

<!-- Ejemplo (borrar al usar):

### 2026-05-08 — No marcar completo sin correr los tests

- **Síntoma**: tarea cerrada como "lista" pero CI falló al hacer push.
- **Causa raíz**: salté la verificación porque el cambio "se veía obvio".
- **Regla**: ejecutar `pnpm test` (o equivalente) antes de marcar cualquier tarea como completed, sin excepción.
- **Disparador**: cualquier cambio de código que toque archivos con tests asociados.

-->
