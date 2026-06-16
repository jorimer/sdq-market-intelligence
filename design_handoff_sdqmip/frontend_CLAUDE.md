# Frontend — SDQ·MIP (instrucciones de diseño)

> **Antes de tocar UI, lee `frontend/DESIGN_SYSTEM.md`.** Es el contrato de diseño
> (dirección “Claro & Vivo” + identidad “Arco”). La fuente de verdad visual es el
> prototipo de alta fidelidad recreado en HTML/React (proyecto de diseño,
> `ui_kits/sdqmip-app/`). Recrea ese diseño dentro de este stack — no copies el HTML.

## Stack
React 18 · Vite · TypeScript (strict) · Tailwind 3 (`darkMode: 'class'`) · Recharts · lucide-react · react-router-dom · react-i18next · axios.

## Fundaciones (ya provistas — aplícalas)
- `tailwind.config.js`: colores mapeados a CSS vars, fuentes, radios, sombras, `darkMode:'class'`.
- `src/index.css`: tokens claro/oscuro (`:root`/`.dark`) + clases base (`.card`, `.btn-*`, `.field`, `.chip`).
- Fuentes en `index.html`: Plus Jakarta Sans · Inter · JetBrains Mono.

## Reglas duras (no negociables)
1. **Colores solo vía tokens/vars.** Nada de hex hardcodeado → el modo oscuro debe funcionar sin tocar marcado.
2. **Cabeceras a una línea.** Títulos de tarjeta/sección/detalle: `truncate`; su columna `min-w-0 flex-1`; icono y acciones `shrink-0`. Nombres dinámicos largos van en el **subtítulo**, no en el título. (Evita el solapamiento título↔subtítulo por carrera de carga de fuentes.)
3. **Cuatro estados por pantalla**: cargando (skeleton) · vacío · error · sin permiso. Copy contextual en español.
4. **Cifras tabulares** (`tabular-nums` / mono) en todo dato.
5. **Charts theme-aware**: colores leídos de `var(--c1…--c6)`, grilla `var(--grid)`. Recharts para línea/área/barras/scatter/radar; SVG propio para gauge, heatmap, treemap, cartograma de mosaicos, distribución, scenario-fan, driver bars.
6. **Sin emoji, sin gradientes decorativos, sin tarjetas con borde-acento a la izquierda, sin slop.**
7. **Tipografía**: Jakarta (display) · Inter (cuerpo) · JetBrains Mono (cifras/etiquetas). Mínimo 12px; métricas clave ≥24px.
8. **i18n**: strings de UI en español (`react-i18next`); identificadores en inglés.
9. **Persistir** tema, ruta, período y ámbito en localStorage.
10. **Hit targets ≥44px** en móvil; sidebar → rail (tablet) → drawer (móvil).

## Orden de construcción
1. Armazón: Sidebar (3 grupos: Ejes · Herramientas · Plataforma) + Topbar (período · ámbito · exportar · ⌘K · tema · perfil) + breadcrumbs + toggle claro/oscuro persistente.
2. Primitivas compartidas en `src/shared/ui/` (Button, Card, CardHead, Badge[Rating/Band/Grade], Field, Tabs, Segmented, StatTile, Gauge, States, Toast, Delta).
3. Cada eje como módulo en `src/modules/{module}/` con el **patrón canónico**: índice/score · desglose explicable · listado/ranking · detalle. Consume `/api/v1/{module}/` (axios), no datos mock.

## Estructura
- `src/shared/ui/` — primitivas.   `src/shared/layout/` — shell.   `src/shared/charts/` — viz.
- `src/modules/{module}/pages/` + `components/` — pantallas por eje (banking_score, macro, sectorial, regulatory, social, trade, esg).
- Mantén la independencia de módulos del backend; el frontend de cada eje vive en su módulo.

> Detalle exhaustivo (tokens exactos, escalas de rating/bandas, catálogo de componentes,
> patrón de eje, identidad Arco, mapa prototipo→repo): **`frontend/DESIGN_SYSTEM.md`**.
