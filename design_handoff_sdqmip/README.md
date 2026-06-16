# Handoff de diseño — SDQ·MIP (dirección “Claro & Vivo” + identidad Arco)

Este paquete integra la **dirección de diseño aprobada** en el flujo del repo
`sdq-market-intelligence/` para que **Claude Code la siga al construir el frontend real**.

## Qué es esto

El prototipo de alta fidelidad vive en este proyecto de diseño, en
`ui_kits/sdqmip-app/` (React + Babel en el navegador). Es la **fuente de verdad
visual**: recrea toda la plataforma (los 7 ejes, herramientas, reportes, sistema
de diseño, identidad, estados). El recorrido completo está en
`Recorrido del Sistema — SDQMIP.html`.

Los archivos de este paquete son **referencias de diseño**, no código de
producción para copiar tal cual. La tarea de Claude Code es **recrear estas
pantallas dentro del stack existente** del repo (React 18 + Vite + TypeScript +
Tailwind + Recharts + lucide-react + react-i18next), respetando sus patrones
(módulos en `frontend/src/modules/`, strings en español, etc.).

**Fidelidad: alta (hi-fi).** Colores, tipografía, espaciado y componentes son
finales. Reprodúcelos con precisión usando las librerías del repo.

## Dónde va cada archivo (cópialos al repo)

| Archivo en este paquete | Destino en el repo | Qué hace |
|---|---|---|
| `frontend_CLAUDE.md` | `frontend/CLAUDE.md` | Instrucciones que Claude Code **auto-lee** al trabajar en `frontend/`. Reglas duras + puntero al sistema. |
| `DESIGN_SYSTEM.md` | `frontend/DESIGN_SYSTEM.md` | Especificación completa del sistema de diseño (tokens, tipografía, componentes, layout, charts, estados, reglas críticas). |
| `tailwind.config.js` | `frontend/tailwind.config.js` | **Reemplaza** el actual. Mapea colores a CSS vars, fuentes, radios, sombras, `darkMode: 'class'`. |
| `index.css` | `frontend/src/index.css` | **Reemplaza** el actual. Tokens claro/oscuro (`:root` / `.dark`) + clases base de componentes. |
| `CLAUDE.addendum.md` | pegar en `CLAUDE.md` (raíz) | Sección “Design System” para el CLAUDE.md raíz, que apunta al de `frontend/`. |

> También conviene agregar las fuentes (Plus Jakarta Sans, Inter, JetBrains Mono)
> en `frontend/index.html` — ver snippet en `DESIGN_SYSTEM.md`.

## Orden sugerido para Claude Code

1. Lee `frontend/DESIGN_SYSTEM.md` completo.
2. Aplica `tailwind.config.js` + `src/index.css` + fuentes en `index.html`.
3. Construye el **armazón** (sidebar de 3 grupos + topbar + breadcrumbs + tema claro/oscuro persistente) antes que las pantallas.
4. Implementa cada eje con el patrón canónico: índice/score · desglose explicable · listado/ranking · detalle.
5. Respeta las **reglas críticas** (cabeceras a una línea, los 4 estados por pantalla, cifras tabulares, charts theme-aware).

## Referencia viva

- Prototipo navegable: `ui_kits/sdqmip-app/index.html` (en el proyecto de diseño).
- Recorrido/visión global: `Recorrido del Sistema — SDQMIP.html`.
- Capturas por pantalla: `screenshots/recorrido/`.
