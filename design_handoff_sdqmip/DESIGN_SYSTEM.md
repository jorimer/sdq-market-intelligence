# SDQ·MIP — Sistema de diseño (canon)

> Dirección visual aprobada: **“Claro & Vivo”** + identidad **“Arco”**.
> Fuente de verdad: el prototipo `ui_kits/sdqmip-app/` del proyecto de diseño.
> Este documento es el contrato de diseño para el frontend (`frontend/`).
> Stack: React 18 · Vite · TypeScript · Tailwind 3 (`darkMode: 'class'`) · Recharts · lucide-react · react-i18next.

---

## 0. Principios

1. **Explicabilidad visible.** Todo número se acompaña de su desglose (drivers, pesos, percentil). Nunca “caja negra”.
2. **Un motor, distinta materia.** Los 7 ejes comparten la misma gramática de UI: índice/score → desglose → ranking → detalle.
3. **Claro por defecto, navy solo para texto, azul eléctrico como acento.** Superficies claras; el color comunica estado, no decora.
4. **Densidad de terminal financiera** (Koyfin / Linear / Trading Economics), no dashboard genérico. Cifras tabulares, jerarquía tipográfica fuerte, sin slop.
5. **Tema claro/oscuro real** vía tokens; ambos son ciudadanos de primera clase.
6. **Sin emoji. Sin gradientes decorativos. Sin tarjetas con borde-acento a la izquierda.** Mínimo viable de cromo.

---

## 1. Tokens (CSS variables)

Definir en `src/index.css`. Toda la UI consume **variables**, nunca hex sueltos.

### Claro (`:root`)
```
--canvas:#F5F8FC;  --surface:#FFFFFF;  --surface-2:#F1F5FB;
--ink:#0A1A3A;     --body:#43506B;     --muted:#76829C;   --faint:#9AA6BF;
--border:#E7ECF3;  --border-strong:#D6DEEC;
--accent:#1E6FFF;  --accent-hover:#1A60E0; --accent-soft:#EAF1FF; --accent-ink:#1551C0;
--teal:#0F7E7E;    --teal-soft:#E3F2F2;
--ok:#15875A;   --ok-soft:#E5F3EC;
--warn:#B7791F; --warn-soft:#FBF1DD;
--alert:#C8392E;--alert-soft:#FBEAE8;
--shadow-card:0 1px 2px rgba(10,26,58,.05), 0 10px 24px -18px rgba(10,26,58,.22);
--shadow-pop:0 8px 28px -8px rgba(10,26,58,.22), 0 2px 8px -2px rgba(10,26,58,.12);
/* data-viz */ --c1:#1E6FFF; --c2:#0F7E7E; --c3:#7A5AF8; --c4:#B7791F; --c5:#E0729A; --c6:#2BA8A8;
--grid:#EAEFF6;
```

### Oscuro (`.dark`)
```
--canvas:#0A0F1C;  --surface:#121B2E;  --surface-2:#182238;
--ink:#EAF0FB;     --body:#AEB9D2;     --muted:#6E7C9B;   --faint:#55617E;
--border:#232F49;  --border-strong:#2E3C5A;
--accent:#3B82F6;  --accent-hover:#5A96F8; --accent-soft:rgba(59,130,246,.15); --accent-ink:#93BBFB;
--teal:#2DD4BF;    --teal-soft:rgba(45,212,191,.14);
--ok:#34D399;   --ok-soft:rgba(52,211,153,.14);
--warn:#FBBF24; --warn-soft:rgba(251,191,36,.14);
--alert:#F2645A;--alert-soft:rgba(242,100,90,.15);
--shadow-card:0 1px 2px rgba(0,0,0,.3), 0 12px 28px -18px rgba(0,0,0,.6);
--shadow-pop:0 10px 34px -8px rgba(0,0,0,.7);
--c1:#3B82F6; --c2:#2DD4BF; --c3:#A78BFA; --c4:#FBBF24; --c5:#F472B6; --c6:#22D3EE;
--grid:#1E2940;
```

El tema se aplica con `document.documentElement.classList.toggle('dark', isDark)` y se **persiste en localStorage** (`sdq_dark`). Respetar `prefers-color-scheme` en el primer arranque es opcional pero recomendado.

---

## 2. Tipografía

- **Display / títulos:** `Plus Jakarta Sans` (700/800), `letter-spacing:-0.02em`.
- **Cuerpo / UI:** `Inter` (400/500/600).
- **Cifras / código / etiquetas técnicas:** `JetBrains Mono` (400/500/600), `font-variant-numeric: tabular-nums`.

Cargar en `frontend/index.html`:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

### Roles
| Rol | Fuente / tamaño / peso |
|---|---|
| Page title (h1) | Jakarta 26px / 800 / `leading-tight` |
| Section / card title (h3) | Jakarta 15px / 700 |
| Eyebrow / kicker | Mono 10–11px / 600 / uppercase / `tracking .12–.2em` / color accent |
| Body | Inter 13–14px / 400–500 / `line-height 1.5` |
| Caption / sub | Inter 12px / `--muted` |
| Métrica grande | Jakarta o Mono 24–34px / 700–800, tabular |
| Dato en tabla / score | Mono, tabular |

Mínimos: nunca <12px en UI; cifras clave ≥24px.

---

## 3. Color semántico

- **Acento** = navegación activa, enlaces, foco, primario. Azul eléctrico.
- **Estados:** `ok` (positivo/fuerte), `warn` (vigilar), `alert` (crítico/débil). Usar siempre la pareja color + `*-soft` (fondo).
- **Teal** = acento secundario para data-viz / segundo índice.

### Bandas de índice (score 0–100)
`Fuerte ≥85` (ok) · `Sólido 70–84` (accent) · `Vigilar 55–69` (warn) · `Débil <55` (alert).
Para ejes de **riesgo** (IRMP/RRI) la escala se invierte semánticamente: **mayor = menor riesgo**; banda “Riesgo Moderado”, etc. Mantener una función `bandFor(score)` y `riskBandFor(score)`.

### Escala de rating SDQ (financiero)
`SDQ-AAA · SDQ-AA+ · SDQ-AA · SDQ-A+ · SDQ-A · SDQ-BBB … SDQ-D`. Badge con color por banda (verde → azul → ámbar → rojo).

### Grado-potencial sectorial (SGPS)
Letras `A…D` para sectorial. Badge tipo “grade”.

### Paleta data-viz
`--c1…--c6` (theme-aware). No usar más de 6 series; reusar en orden.

---

## 4. Armazón de la app (construir primero)

### Sidebar (252px expandido · 64px colapsado · drawer en móvil)
Tres grupos con encabezado mono-uppercase-faint:
1. **Ejes de inteligencia** — los 7: Financiero, Macroeconómico, Sectorial, Regulatorio & político, Social & desarrollo, Comercio exterior, ESG & clima. Iconos lucide: `landmark, line-chart, layout-grid, scale, users, ship, leaf`.
2. **Herramientas** — Deal Scoring (`target`), Market Brief (`sparkles`).
3. **Plataforma** — Resumen ejecutivo (`layout-dashboard`), Comparador (`git-compare`), Alertas (`bell`), Publicaciones (`newspaper`), Reportes (`files`), Metodología (`book-open`), API & embebido (`code-2`), Configuración (`settings`), Sistema de diseño (`swatch-book`), Identidad (`shapes`).

Item activo: fondo `--accent-soft`, texto `--accent-ink`, barra lateral de 3px `--accent`, icono `--accent`.

### Topbar (58px)
Izq: toggle colapso/hamburguesa + breadcrumbs (`SDQ·MIP › Eje › Detalle`).
Der: selector **Período** (mono, ej. `2024-Q4`), selector **Ámbito** (RD / Centroamérica / Caribe / región), menú **Exportar/Compartir** (PDF/PNG/CSV/enlace/programar, con toast), buscador global **⌘K**, toggle **claro/oscuro**, campana de alertas, avatar de perfil.

Período y Ámbito viven en **contexto global** y reetiquetan todas las pantallas.

### Búsqueda global (⌘K)
Palette modal: input + resultados de entidades/sectores/países con su score. `Esc` cierra.

### Responsive
- **≥1024 (desktop):** sidebar completo, colapsable manual.
- **768–1023 (tablet):** sidebar en **rail** de iconos (auto).
- **<768 (móvil):** **drawer** off-canvas con backdrop + hamburguesa; topbar y tablas se adaptan.

Ruta y tema persistidos en localStorage (`sdq_route`, `sdq_dark`, `sdq_period`, `sdq_scope`).

---

## 5. Patrón canónico de eje

Cada eje se compone de **lista** + **detalle**, parametrizados por datos (un `AxisView`/`AxisDetail` genérico + override solo donde el dominio lo exige: Macro tiene sub-tabs; Comercio/ESG/Social/Sectorial tienen visualizaciones a medida).

**Lista de eje:** header (eyebrow con fuentes, título = nombre del índice, blurb), tira de KPIs, una visualización principal (matriz/treemap/cartograma/gauge según eje), y un **ranking** en tabla (ítem · score · banda · cambio · sparkline).

**Detalle:** hero (nombre + badge + gauge + banda + percentil + acciones Reporte/Comparar) y tabs:
- **Desglose explicable:** Drivers (±), Sub-componentes ponderados, Perfil radar vs. conjunto, y **narrativa del analista** (marco SCQA).
- **Indicadores:** tabla de indicadores normalizados.
- **Tendencia & pares:** serie temporal + ranking de pares.

Ejes y su materia: Financiero=entidades (SIB), Macro=indicadores (BCRD) con sub-tabs (Resumen/Series/Indicadores/Escenarios/Mapa de calor/Regional), Sectorial=sectores (IAI/SGPS), Regulatorio=países (IRMP) + RRI por sector, Social=regiones (IDS, con **distribución**), Comercio=flujos (ICE), ESG=sectores/regiones (IEC).

---

## 6. Componentes

Construir como componentes React tipados en `frontend/src/shared/ui/`. Clases base en `index.css`.

| Componente | Notas |
|---|---|
| **Button** | Variantes: `primary` (bg accent), `ghost` (borde), `soft` (accent-soft). Icono opcional izq/der (lucide). 36–38px alto, radio 10px, peso 600. |
| **Card** | `bg-surface`, borde `--border`, radio 16px, `shadow-card`. |
| **CardHead** | icono(30px, accent-soft) + columna(título h3 + subtítulo). **Ver §8 reglas críticas.** Slot `right` para acciones/badges. |
| **PageHead** | eyebrow + h1 + sub (`max-w-2xl`) + slot `right`. |
| **Chip / Tag** | píldora 12px, borde suave; variante con punto de estado. |
| **Badge** | `RatingBadge` (escala SDQ), `BandBadge` (banda de índice), `GradeBadge` (A…D). Color por banda. |
| **Input / Field** | borde `--border-strong`, foco con anillo `--accent-soft`. |
| **Tabs** | subrayado activo en accent. |
| **Segmented** | control de 2–3 opciones (ej. Base 100 / Valor). |
| **StatTile** | etiqueta + métrica grande tabular + delta con flecha y color de signo. |
| **Gauge** | arco 0–100 (SVG propio), color por banda; es el motivo del logo. |
| **Tooltip** | `[data-tip]`, fondo `--ink`. |
| **Skeleton** | shimmer con `--surface-2`/`--border`. |
| **Toast** | inferior-centro, fondo `--ink`. |
| **Delta** | `+/−` con flecha; verde sube / rojo baja / gris neutro. Tabular. |

---

## 7. Data-viz (Recharts + SVG propio)

- Colorear **siempre** vía CSS vars (`var(--c1)`, `var(--grid)`, `var(--muted)`) para que el tema funcione solo. Pasar colores por prop leídos de las vars; no hardcodear hex en los charts.
- **Recharts** para: área/línea, barras, multi-serie (base 100), scatter (bubble matrix), radar (donde aplique).
- **SVG propio** (componentes a medida) para piezas que Recharts no resuelve bien con esta estética: **gauge de arco**, **heatmap** (indicador×trimestre / sector×dimensión), **treemap** squarified (exportaciones, sub-sectores), **tile cartogram / cartograma de mosaicos** (resiliencia climática, mosaico territorial — **sin geografía falsa**), **distribución** por buckets, **scenario fan** (banda optimista–adverso), **driver bars** (±), **dim meters** (sub-componentes ponderados), **rank bars**, **sparkline**.
- Ejes/tooltips sobrios; sin sombras pesadas; grilla `--grid` tenue. Cifras tabulares.
- No dibujar mapas geográficos reales: usar cartogramas de mosaicos etiquetados.

---

## 8. Reglas críticas de implementación (no negociables)

> Estas reglas evitan los bugs que se cazaron en el barrido de cierre del prototipo.

1. **Cabeceras a una sola línea.** En `CardHead`, `DocHeader`, héroes de detalle, widgets embebidos y cualquier header con `flex justify-between`:
   - El **título** va en **una línea** con `truncate` (`overflow-hidden text-ellipsis whitespace-nowrap`).
   - La **columna de texto** lleva `min-w-0 flex-1`; el icono y el contenido `right` llevan `shrink-0`.
   - **Nunca** dejar que un título envuelva junto a un badge/botón hermano: el desfase entre métrica de fuente fallback y webfont produce **solapamiento** del título sobre el subtítulo justo en el borde de wrap.
   - Si el nombre es **dinámico y largo** (entidad/región/sector), ponlo en el **subtítulo** (que sí envuelve), no en el título. Ej.: título `Sub-componentes`, subtítulo `Distrito Nacional · ponderados`.
2. **Subtítulos** pueden envolver; déjalos en flujo normal debajo, con `mt`.
3. **Cuatro estados por pantalla**, siempre: `cargando` (skeletons), `vacío`, `error`, `sin permiso`. Componente `StateBlock` con título en **una línea** (`whitespace-nowrap` en títulos cortos de estado). Copy contextual por ruta.
4. **Cifras tabulares** en todo dato numérico (`tabular-nums` / clase mono).
5. **Tema por tokens**: nunca colores hardcodeados; todo vía vars para que `.dark` funcione.
6. **Charts theme-aware** (ver §7).
7. **Hit targets** ≥44px en móvil.
8. **Persistencia** de tema, ruta, período y ámbito en localStorage.
9. **i18n**: strings en español vía `react-i18next`; identificadores en inglés.

---

## 9. Identidad “Arco”

Logo = arco abierto (la aguja de un gauge 0–100) + punto (el dato/señal). Resume el producto.

Favicon / mark (SVG):
```html
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="9" fill="#1E6FFF"/>
  <g transform="translate(16 16)">
    <circle r="8" fill="none" stroke="white" stroke-width="3.4" stroke-linecap="round"
            stroke-dasharray="50.2" stroke-dashoffset="13" transform="rotate(-90)"/>
    <circle cy="-8" r="2.4" fill="white"/>
  </g>
</svg>
```
Wordmark: `SDQ·MIP` (Jakarta 800; `·MIP` en `--muted`). En la app el arco puede animarse como medidor.
⚠️ No hay logo oficial de SDQ: la identidad Arco es **propuesta de producto**. Hay 4 direcciones exploradas (Arco · Mira · Índice · Cuadrante); **Arco** es la recomendación.

---

## 10. Contenido y tono

- UI en **español**; tono institucional, preciso, sobrio. Sin marketing vacío.
- **Sin slop**: nada de stats/íconos de relleno; cada elemento gana su lugar. Menos es más.
- Datos del prototipo son **ilustrativos**; nombres reales (RD/región) por realismo. En producción, datos de SIB, BCRD, ONE, DGA, WGI.
- Marco narrativo: **SCQA** para lecturas de analista (generadas con Claude).

---

## 11. Mapa prototipo → repo

| Prototipo (`ui_kits/sdqmip-app/`) | Repo |
|---|---|
| `index.html` (tokens + Tailwind config) | `src/index.css` + `tailwind.config.js` |
| `primitives.jsx` (Button, Card, CardHead, Badge, States…) | `src/shared/ui/` |
| `shell.jsx` (Sidebar, Topbar, Search) | `src/shared/layout/` |
| `charts.jsx`, `charts_macro.jsx` | `src/shared/charts/` (Recharts + SVG propio) |
| `data*.jsx` | reemplazar por llamadas a `/api/v1/{module}/` (axios) |
| `screens_*` por eje | `src/modules/{module}/pages/` + `components/` |
| QA state gate | hook/HOC de estados reutilizable |

El prototipo usa datos mock locales; en el repo cada eje es un **módulo** que consume su API (`/api/v1/{module}/`). Mantener la **independencia de módulos** y la comunicación por eventos del backend; el frontend de cada eje vive en `src/modules/{module}/`.
