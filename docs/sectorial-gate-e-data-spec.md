# Sectorial (IAI) — qué dato falta para un Gate E real

Objetivo de esta hoja: listar **qué indicadores y para qué sectores** hace falta
conseguir para que el índice sectorial (IAI) sea (a) discriminante por sector y
(b) validable con un Gate E. Sirve para buscar fuentes.

## 1. La cobertura: los 17 sectores (cuentas nacionales BCRD, base 2018)

Cualquier indicador nuevo debe venir desglosado **por estos 17 sectores** (o ser
mapeable a ellos sin agrupar varios en uno — el matcher exige cobertura completa,
un relleno parcial distorsiona la normalización min-max):

| slug | sector |
|---|---|
| agropecuario | Agropecuario |
| mineria | Minería y Canteras |
| manufactura_local | Manufactura Local |
| zonas_francas | Manufactura Zonas Francas |
| construccion | Construcción |
| energia | Energía y Agua |
| comercio | Comercio |
| turismo | Turismo (Hoteles/Bares/Rest.) |
| transporte | Transporte y Almacenamiento |
| comunicaciones | Comunicaciones |
| financiero | Intermediación Financiera |
| inmobiliario | Inmobiliario y Alquiler |
| ensenanza | Enseñanza |
| salud | Salud |
| administracion_publica | Administración Pública |
| servicios_profesionales | Servicios Profesionales |
| otros_servicios | Otros Servicios de Mercado |

> Nota de granularidad: las fuentes laborales/educativas suelen usar clasificaciones
> distintas (ONE empleo = 11 actividades CIIU; MESCyT = áreas de conocimiento). Para
> servir aquí, una fuente debe separar **manufactura_local / zonas_francas / mineria**
> y los servicios (ensenanza, salud, financiero, etc.), no agruparlos.

## 2. Las variables del IAI y su estado (qué falta volver real, por sector)

Pesos: macro 25% · business 25% · talent 20% · regulation 15% · sector 15%.

| dimensión (peso) | variable | hoy | qué indicador real por sector la llenaría |
|---|---|---|---|
| macro (25%) | macro_exposure | real **solo período actual** (contrato macro→sectorial) | reconstruir el contrato macro por año histórico (ya hay series BCRD) — pieza de ingeniería, no fuente nueva |
| business (25%) | ease_of_business | **rúbrica 50** | costo/facilidad de hacer negocios **por sector** (no el Doing Business nacional, que además se descontinuó) |
| business (25%) | operating_cost (invertida) | **rúbrica 50** | costo operativo por sector: energía, salarios, insumos por rama |
| talent (20%) | labor_availability | **rúbrica 50** | empleo/PEA **por los 17 sectores** (la ENCFT del BCRD por rama, si separa los 17) |
| talent (20%) | skills_index | **rúbrica 50** | nivel educativo/competencias de la fuerza laboral **por sector** |
| regulation (15%) | regulatory_quality | **real (WGI nacional)** ✅ | — (nacional, no diferencia sectores; ya está) |
| regulation (15%) | regulatory_volatility (invertida) | **rúbrica 50** | volatilidad/cambios regulatorios por sector (difícil; podría derivarse de series WGI) |
| sector (15%) | sector_growth | **real (BCRD)** ✅ | — |
| sector (15%) | sector_size | **real (BCRD)** ✅ | — |

**En resumen, para discriminar de verdad faltan 4 variables por sector:**
`ease_of_business`, `operating_cost`, `labor_availability`, `skills_index` — todas
**por los 17 sectores**. Hoy real y diferenciador por sector: solo macro_exposure
(período actual) + sector_growth + sector_size.

## 3. Qué necesita el Gate E específicamente (además del dato de arriba)

El Gate E (backtest) valida que el IAI **predice** algo observable. Dos requisitos:

1. **Que el IAI discrimine sectores** → necesita las 4 variables del §2 con dato
   real por sector (sin eso, ~85% del IAI es rúbrica plana y el índice casi no
   diferencia).
2. **Un desenlace real por sector, NO circular:**
   - El candidato natural —crecimiento del sector en T+1— es **circular**: el IAI
     ya contiene `sector_growth_T` (inercia serial). No sirve solo.
   - Desenlaces independientes a buscar, **por los 17 sectores**:
     - **Inversión extranjera directa (IED) por sector** (datos.gob.do / BCRD / ProDominicana) — el outcome más alineado con "atractivo de inversión".
     - **Empleo formal por sector** (TSS/SDSS o ENCFT) — crecimiento del empleo sectorial T+1.
     - **Exportaciones por sector** (DGA/Comtrade, pero el mapeo HS→17 sectores es parcial).
   - Idealmente con **ventana point-in-time** (IAI en T vs outcome en T+1/T+2) y
     suficientes años (el panel BCRD da 2018-2025 × 17 = ~100 obs, alcanza para
     una validación direccional).

## 4. Prioridad sugerida para cazar fuentes

1. **IED por sector** (desbloquea el Gate E con el outcome más legítimo: atractivo→inversión).
2. **Empleo por los 17 sectores** (llena `labor_availability` + da un 2º outcome).
3. **Costo operativo / clima de negocios por sector** (llena `business`).

Con (1) ya se podría intentar un Gate E direccional aunque el índice siga 60%
rúbrica; con (1)+(2) el IAI empieza a discriminar y el Gate E gana sentido.
