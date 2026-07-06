# Referencias regulatorias — Sector Seguros (RD)

Fuentes normativas públicas que fundamentan las metodologías de `insurance_intel`.
Los PDF no se versionan (tamaño); se enlazan sus fuentes oficiales.

## Ley No. 146-02 sobre Seguros y Fianzas
- Fuente: Superintendencia de Seguros (SIS), Gaceta Oficial No. 10169, 26-sep-2002.
- **Capítulo XII — Márgenes de solvencia, patrimonio técnico ajustado y liquidez mínima** (Arts. 159-167):
  - **Art. 160 — Margen de Solvencia Mínima Requerida (MSMR):** el MAYOR entre
    (a) 27% de las primas retenidas devengadas (5% en salud y vida colectivo) y
    (b) 41% del promedio de siniestros incurridos de 3 años (ex-catastróficos) × factor de
    retención; + 7% de reservas matemáticas (vida individual) + 5% de reaseguro cedido.
    Nunca inferior al capital mínimo requerido.
  - **Art. 161 — Patrimonio Técnico Ajustado (PTA):** capital pagado + reservas de previsión +
    beneficios acumulados − pérdidas + reservas catastróficas + 80% superávit reevaluación +
    otras reservas de capital, menos deducciones (primas > 360 días, inversiones en
    aseguradoras, cuentas por cobrar de holdings/afiliadas, préstamos comerciales).
  - **Índice de Solvencia = PTA / MSMR** (≥ 1 = cumple).
  - **Art. 162 — Liquidez Mínima Requerida (LMR):** fórmula sobre reservas de riesgos en curso,
    siniestros pendientes y reservas matemáticas. **Índice de Liquidez = Disponibilidad Libre de
    Gravamen / LMR** (≥ 1 = cumple).
  - **Art. 164:** la SIS publica trimestralmente el margen de solvencia, el PTA y el índice de
    solvencia de todas las compañías → **superficie `Índices de Solvencia y Liquidez`** (Excel).

## Resolución 04-2024 (SIS)
Adopta los **Principios Básicos de Seguros (Insurance Core Principles, ICP) de la IAIS** como
estándar internacional de regulación y supervisión del sector en RD. Marco de referencia del ISF.

## Resolución 01-2024 (SIS)
Sobre requerimiento y remisión de información de los aseguradores.

## Manual de Contabilidad (nota)
El "Manual de Contabilidad para Entidades Supervisadas" es de la **Superintendencia de Bancos**
(bancos, no aseguradoras); confirma la convención estándar RD de clases contables
(100 Activo · 200 Pasivo · 300 Patrimonio · 400 Ingresos · 500 Gastos), que valida el mapeo del
extractor de estados auditados de aseguradoras (secciones 1=Activo … 5=Gastos).

## Cómo lo usa el código
- `shared/data/sis_solvency_client.py` + `solvency_sync.py`: ingieren el índice de solvencia y
  de liquidez OFICIALES (Art. 164) por aseguradora y los cruzan al roster.
- `scoring/isf.py`: las dimensiones de solvencia y liquidez usan estos índices regulatorios
  (antes proxies de balance); siniestralidad/escala/resultado vienen del auditado.
