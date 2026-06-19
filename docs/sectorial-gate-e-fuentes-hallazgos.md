# Sectorial (IAI) — Hallazgos de fuentes para el Gate E

> Compañero de [`sectorial-gate-e-data-spec.md`](sectorial-gate-e-data-spec.md).
> Investigación de fuentes ejecutada **2026-06-19**. Alcance: las 4 variables
> faltantes (`ease_of_business`, `operating_cost`, `labor_availability`,
> `skills_index`) + los 3 outcomes candidatos (IED, empleo, exportaciones).
> Criterio: **maximizar cobertura** — se aceptan crosswalks y proxies, siempre con
> disclosure del supuesto.
>
> Toda URL citada fue verificada por fetch salvo donde se anota lo contrario.
> Estado de las fuentes ya cerradas (no re-investigadas): BCRD PIB por sector
> (`sector_size`+`sector_growth` ✅), WGI nacional (`regulatory_quality` ✅).

---

## 0. BLUF — lo que cambia tu plan

1. **Ninguna fuente entrega los 17 sectores limpios.** El cuello de botella no es
   disponibilidad de dato — es **granularidad de mapeo**. Cada fuente colapsa un
   subconjunto distinto de los 17. La decisión de diseño más importante que sale de
   esta investigación: **correr el Gate E a la resolución donde el dato existe
   (~8–13 sectores según la variable), no forzar los 17.**

2. **El mejor outcome para desbloquear el Gate E NO es IED — es empleo formal (TSS).**
   El spec priorizó IED por ser "el más alineado con atractivo→inversión". Es cierto
   conceptualmente, pero IED cubre ~8/17 y **fusiona manufactura local con comercio**.
   El empleo formal cotizante de la **TSS** cubre ~12–13/17, es trimestral y es un
   outcome igual de legítimo. Recomendación: **TSS como outcome primario, IED como
   segundo outcome / validación cruzada.**

3. **`ease_of_business` por sector no tiene fuente real en RD.** B-READY (sucesor de
   Doing Business) **(a) es nacional, no sectorial, y (b) aún no cubre RD** — RD entra
   por primera vez en la edición **B-READY 2026**, todavía sin publicar. Esta variable
   queda como **proxy compuesto** (régimen especial + tarifa + informalidad) o rúbrica.
   No persigas más: confirmado que la fuente sectorial no existe.

4. **Corrección a la memoria del proyecto:** el quiebre metodológico laboral es
   **Q3-2014 (ENFT→ENCFT)**, no 2021 como dice `SERIES_CANONICAS_BCRD.md` y el handoff.
   Cualquier serie laboral larga necesita empalme antes de 2014, no antes de 2021.

5. **Hay más dato real disponible de lo que el spec asumía.** `operating_cost` por
   sector es **altamente factible** vía TSS (salario promedio cotizable por actividad,
   ~12–13 sectores) + salario mínimo sectorial diferenciado + tarifas eléctricas. No es
   la variable difícil; la difícil es `ease_of_business`.

---

## 1. Matriz maestra — variable × mejor fuente × veredicto

| Variable IAI | Hoy | Mejor fuente hallada | Cobertura de los 17 | Frecuencia | Point-in-time | Veredicto |
|---|---|---|---|---|---|---|
| `labor_availability` | rúbrica 50 | **ENCFT (BCRD)** + CNZFE (ZF) | ~9 directo / ~12 con crosswalk | trimestral | sí | **Factible vía crosswalk** |
| `operating_cost` | rúbrica 50 | **TSS salario por actividad** + CNS mínimo sectorial + SIE tarifas | ~12–13 | trim. (TSS) | sí | **Altamente factible** |
| `skills_index` | rúbrica 50 | **Censo 2022 (ONE/REDATAM)** educación×rama; ENCFT microdato | ~15–16 (Censo) | estático 2022 | no (foto única) | **Factible, estático** |
| `ease_of_business` | rúbrica 50 | — (B-READY no sirve) | 0 directo | — | — | **Sin fuente; proxy o rúbrica** |
| `regulatory_volatility` | rúbrica 50 | derivar de serie WGI (ingeniería, no fuente) | nacional | anual | — | Derivable, no diferencia sectores |

| Outcome Gate E | Mejor fuente | Cobertura de los 17 | Frecuencia | Point-in-time | Veredicto |
|---|---|---|---|---|---|
| **Empleo formal T+1** | **TSS** (cotizantes por actividad) | ~12–13 | trimestral | sí (cuidar revisión por morosidad) | **Outcome primario recomendado** |
| **IED por sector** | **BCRD** `inversion_ext_sector_6.xls` | ~8 (manuf+comercio fusionados) | anual + trimestral | sí (cachear vintages) | **Outcome secundario / validación** |
| **Exportaciones por sector** | DGA (HS+régimen) + BCRD + CNZFE | ~4 transables (~24%) | mensual/trim. | sí | **Outcome parcial — solo transables** |

---

## 2. Detalle por fuente

### 2.1 IED por sector — BCRD (única fuente primaria)

- **Archivo:** `https://cdn.bancentral.gov.do/documents/estadisticas/sector-externo/documents/inversion_ext_sector_6.xls` (anual + trimestral, 2010–2025; inspeccionado).
- **Taxonomía (10 filas):** Turismo, **Comercio/Industria**, Telecomunicaciones, Energía, Financiero, Zonas Francas, Minero, Inmobiliario, Transporte, Otros (=0 en toda la serie).
- **Mapeo a 17:** directo para mineria, zonas_francas, turismo, inmobiliario, transporte, comunicaciones (=telecom), financiero, energia (incluye agua → OK). **`manufactura_local` y `comercio` vienen fusionados** en "Comercio/Industria" (no separables). Sin dato: agropecuario, construccion, ensenanza, salud, administracion_publica, servicios_profesionales, otros_servicios.
- **Cobertura limpia: 7–8 de 17.** ProDominicana republica estas mismas cifras (no es fuente independiente — usar el Excel BCRD directo). datos.gob.do **no** tiene IED.
- **Point-in-time:** viable, pero las cifras se revisan retroactivamente → hay que **cachear cada release** (no hay archivo de vintages).

### 2.2 Empleo por sector — ENCFT (BCRD) + TSS + CNZFE

- **ENCFT (BCRD)** — `https://www.bancentral.gov.do/a/d/2541-encuesta-continua-encft`. Población ocupada por **12 ramas CIIU**, trimestral. Nota al pie verificada: "Industrias" **incluye minas y canteras** → manufactura_local + zonas_francas + minería colapsadas en una sola rama. "Transporte y Comunicaciones" mezcla 2 sectores; "Otros Servicios" absorbe inmobiliario + servicios_profesionales + otros_servicios. **Quiebre Q3-2014** (ENFT→ENCFT). Microdato solo por solicitud FOIA, no descarga abierta. **Cobertura: ~9 directo / ~12 marcados con crosswalk.**
- **TSS** — empleo **formal** cotizante por actividad económica. CSV abierto (`https://datos.gob.do/es/dataset/trabajadores-activos-en-tss`) trae solo total por tipo de empleador; **el desglose por rama vive en los boletines trimestrales PDF** (hay que extraerlos). Ventaja sobre ENCFT: separa manufactura vs construcción vs servicios con más detalle. Es el outcome conceptualmente ideal para "empleo formal T+1".
- **CNZFE** — `https://datos.gob.do/dataset/principales-variables-del-sector-de-zonas-francas-de-la-republica-dominicana-2006-2025` (ODbL, anual). **Resuelve `zonas_francas`** que la ENCFT no separa. Crosswalk clave: `manufactura_local ≈ ENCFT "Industrias" − minería(proxy) − empleo_ZF(CNZFE)`.

### 2.3 Skills por sector — Censo 2022 (ONE) como mejor opción

- **Censo 2022 (ONE/REDATAM)** — único cruce verificable **nivel de instrucción × rama CIIU**, granularidad CIIU Rev.4 que sí separa minería/manufactura/inmobiliario/servicios profesionales. **Cobertura ~15–16/17.** Limitación: **estático 2022** (censo decenal) y requiere construir el tabulado en REDATAM (no confirmé que el procesador en línea esté operativo). zonas_francas es el único difícil (el censo no marca régimen).
- **ENCFT microdato** — mismo cruce, trimestral/actualizable, pero las 12 ramas no separan minería/manuf/ZF y el microdato no es descarga abierta (gestionar con BCRD).
- **MESCyT** (`https://mescyt.gob.do/.../ESTADISTICAS-...-2022.pdf`) — egresados por **13 áreas de conocimiento**, no por sector. Crosswalk área→sector es many-to-many y débil; limpio solo para enseñanza y salud. **Proxy-only.** INFOTEP no publica desglose por familia profesional en abierto. **Recomendación:** skills_index = "% ocupados con educación terciaria (o años de escolaridad) por rama" desde Censo 2022, con crosswalk CIIU→BCRD-2018 documentado.

### 2.4 Costo operativo por sector — TSS + CNS + SIE (la variable fácil)

- **TSS salario promedio cotizable por actividad** ★★ — la mejor cobertura sectorial (~12–13/17), salario formal real (no solo mínimo). Valores 2025 verificados: minería RD$74,788 · financiero 61,414 · energía 51,034 · comunicaciones 47,781 · enseñanza 42,365 · admin pública 41,774 · construcción 39,368 · salud 38,863 · transporte 38,819. **Bonus:** el mismo corte trae **tasas de informalidad por sector** (proxy inverso de facilidad de formalización): agro 80–85%, construcción 70–75%, comercio 55–60%, industria 30–35%, financiero ~20%.
- **Salario mínimo sectorial (CNS / Min. Trabajo)** — RD tiene mínimo **legalmente diferenciado**: zonas francas (RD$20,875), hoteles/casinos (21,840), restaurantes (21,000), campo (714.60/jornada), construcción (escala a destajo), vigilancia (24,633), resto "no sectorizado" por tamaño. Diferenciador directo para ~5–6 sectores.
- **Tarifas eléctricas (SIE)** — categoría **MTD-2 = "Zonas Francas e Industrial"** vs MTD-1 (comercio) vs BTD/BTS. Diferenciador energético para zonas_francas/manufactura/comercio/turismo. Limitación: valores en **PDF escaneado** (requiere OCR de la resolución vigente).

### 2.5 ease_of_business — sin fuente sectorial

- **B-READY (Banco Mundial)** — **(a)** nacional, no sectorial (10 temas funcionales, no sectores); **(b) RD no está cubierta hasta B-READY 2026**, aún sin publicar. No usable para diferenciar sectores. Confirmado contra la lista oficial de economías cubiertas.
- **CNC / ProDominicana / State Dept Investment Climate** — cualitativos, sin score sectorial cuantitativo.
- **Salida realista:** proxy compuesto = (i) existencia de régimen especial (Ley 8-90 zonas francas, CONFOTUR turismo, Ley 57-07 renovables) + (ii) tarifa eléctrica diferenciada + (iii) informalidad sectorial. Con disclosure de que es un índice construido, no un indicador oficial. O dejar `ease_of_business` como rúbrica y absorber su 12.5% en las otras variables business.

### 2.6 Exportaciones por sector — solo transables

- **DGA** (`https://www.aduanas.gob.do/datos-abiertos/`, ODbL) — exportaciones por capítulo HS-2 (2017–2026) + dataset "por régimen" que separa **nacional vs zonas francas** a nivel agregado. El archivo por capítulo NO está cruzado con régimen.
- **BCRD** — ancla a base 2018; mejor split nacional/ZF/minería/agro (ZF = 60.7% del total exportado 2024).
- **CNZFE** — desagrega ZF por actividad (médicos 32.8%, tabaco 15.7%, eléctricos 13.7%, textil 9.8%), pero **anual con lag ~6 meses**.
- **Comtrade** — HS-6 más granular pero **no separa régimen** (no distingue manuf local de ZF). Secundaria.
- **Cobertura: solo 4/17 transables** (agropecuario, mineria, manufactura_local, zonas_francas). turismo capturable vía exportación de servicios (BoP BCRD, mensual). Los 10 sectores de servicios restantes no se exportan como bienes.

---

## 3. Recomendación de secuencia (qué hacer con esto)

**Fase 1 — desbloquear el Gate E (mayor palanca, menor fricción):**
1. **Outcome: empleo formal TSS** por actividad, trimestral. Cubre ~12–13 sectores —
   más que IED. Requiere scraper de boletines PDF (no hay CSV sectorial). Rezagar ≥1
   trimestre por la revisión al alza por morosidad de empleadores.
2. **Input: `operating_cost`** desde TSS salario por actividad (misma extracción) +
   salario mínimo sectorial. Es la variable real más barata de conseguir y ya
   discrimina ~12 sectores.
3. Con (1)+(2) el IAI deja de ser ~85% rúbrica plana y el Gate E direccional ya tiene
   varianza que validar.

**Fase 2 — segundo outcome y robustez:**
4. **IED por sector (BCRD)** como outcome independiente / validación cruzada, a su
   resolución de ~8 sectores. Cachear cada release para point-in-time honesto.
5. **`labor_availability`** desde ENCFT + CNZFE (crosswalk Industrias − ZF − minería).

**Fase 3 — refinamiento:**
6. **`skills_index`** desde Censo 2022 (construir tabulado REDATAM educación×rama).
   Verificar primero que el procesador REDATAM esté operativo en línea.
7. **`ease_of_business`** → proxy compuesto o dejar en rúbrica. No hay fuente sectorial.
8. **Exportaciones** como outcome solo para los 4 sectores transables (panel separado).

**Decisión de arquitectura pendiente (tuya):** ¿el Gate E corre a 17 sectores
(forzando imputación en los que ninguna fuente cubre) o a la resolución BCRD-aligned
de ~8–13 donde el dato es real? Mi posición: **correr a la resolución real y declarar
los sectores no-cubiertos como fuera de validación**, antes que imputar y validar
contra ruido.

---

## 4. Verificaciones pendientes (incertidumbre honesta)

- ¿El microdato ENCFT es descarga abierta o solo FOIA? Condiciona el skills_index actualizable.
- ¿El procesador REDATAM del Censo 2022 está operativo en línea? Condiciona la mejor fuente de skills.
- ¿El boletín TSS etiqueta "zona franca" como rama separada? Si no, pedir el corte específico a la TSS.
- ¿La API BCRD (`apibcrd.bancentral.gov.do`) expone la serie de IED por sector programáticamente, o solo el Excel?
- Valores numéricos de tarifas SIE: PDF escaneado → requieren OCR de la resolución vigente.

## Fuentes

- [BCRD — Sector Externo / IED](https://www.bancentral.gov.do/a/CustomView/2532-sector-externo) · [IED por sector (xls)](https://cdn.bancentral.gov.do/documents/estadisticas/sector-externo/documents/inversion_ext_sector_6.xls)
- [BCRD — ENCFT](https://www.bancentral.gov.do/a/d/2541-encuesta-continua-encft) · [Boletín laboral jul-sep 2025](https://cdn.bancentral.gov.do/documents/publicaciones-economicas/boletin-trimestral-del-mercado-laboral/documents/Boletin_Trimestral_Mercado_Laboral_jul-sep_2025.pdf)
- [TSS — empleos cotizantes (datos.gob.do)](https://datos.gob.do/es/dataset/trabajadores-activos-en-tss) · [TSS — salario promedio por sector](https://tss.gob.do/salario-promedio-de-cotizantes-en-la-seguridad-social-supera-los-rd38-mil/)
- [CNZFE — variables ZF 2006-2025](https://datos.gob.do/dataset/principales-variables-del-sector-de-zonas-francas-de-la-republica-dominicana-2006-2025)
- [ONE — Censo 2022](https://www.one.gob.do/publicaciones/2024/informe-general-del-x-censo-nacional-de-poblacion-y-vivienda-2022/)
- [MESCyT — Estadísticas Educación Superior 2022](https://mescyt.gob.do/wp-content/uploads/2025/10/INFORME-GENERAL-SOBRE-ESTADISTICAS-DE-EDUCACION-SUPERIOR-CIENCIA-Y-TECNOLOGIA-2022.pdf)
- [Comité Nacional de Salarios — resoluciones](https://transparencia.mt.gob.do/index.php/base-legal/category/2025)
- [SIE — Superintendencia de Electricidad](https://sie.gob.do/)
- [World Bank — B-READY economías cubiertas](https://www.worldbank.org/en/businessready/about-us/covered-economies)
- [DGA — datos abiertos](https://www.aduanas.gob.do/datos-abiertos/) · [UN Comtrade](https://comtradeplus.un.org/)
