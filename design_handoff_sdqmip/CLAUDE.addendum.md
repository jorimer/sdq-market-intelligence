<!-- Pegar esta sección en el CLAUDE.md de la raíz del repo (sdq-market-intelligence/CLAUDE.md). -->

## Design System (frontend)

La UI sigue la dirección **"Claro & Vivo" + identidad "Arco"**. El contrato de
diseño completo está en **`frontend/DESIGN_SYSTEM.md`**, y las instrucciones
operativas para trabajar en la UI en **`frontend/CLAUDE.md`** (se auto-cargan al
editar `frontend/`).

Reglas duras al tocar frontend:
- Colores **solo vía CSS vars/tokens** (`src/index.css`); el modo claro/oscuro debe funcionar sin tocar marcado (`darkMode: 'class'`).
- Cabeceras de tarjeta/sección/detalle **a una línea** (`truncate`, columna `min-w-0 flex-1`, acciones `shrink-0`); nombres dinámicos largos van en el subtítulo.
- **Cuatro estados** por pantalla: cargando · vacío · error · sin permiso.
- **Cifras tabulares**; charts **theme-aware** (colores desde `var(--c1…--c6)`).
- Tipografía: Plus Jakarta Sans (display) · Inter (cuerpo) · JetBrains Mono (cifras).
- Sin emoji, sin gradientes decorativos, sin slop. UI en español.
- Cada eje sigue el patrón: **índice/score · desglose explicable · listado/ranking · detalle**.

Fuente de verdad visual: prototipo de alta fidelidad `ui_kits/sdqmip-app/`
(proyecto de diseño) — recrear, no copiar el HTML.
