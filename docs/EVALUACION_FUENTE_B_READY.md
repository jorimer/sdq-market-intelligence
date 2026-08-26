# Evaluación de fuente — Business Ready (B-READY) del Banco Mundial

**Estado: investigación de fuente. NO se escribió código de integración ni se tocó el Data
Registry.** La decisión de qué se integra y cuándo es del dueño.

Evidencia recogida el **2026-08-23** contra los archivos reales de la edición 2025
—descargados y leídos, no navegados— y contra la página de publicaciones del emisor.

---

## 0. BLUF

| | |
|---|---|
| **Veredicto hoy** | **NO integrable.** La República Dominicana no está entre las 101 economías de la edición 2025 |
| **Cuándo puede cambiar** | El emisor anuncia una edición completa en **2026** que «dará cobertura global ampliada y concluirá el período de despliegue». No publica la lista de economías que se suman |
| **Qué NO resuelve, ni cuando entre** | No reemplaza a los índices del WEF que dejaron sin instrumento a cinco indicadores de la END 2030. Mide otra cosa y en otra escala |
| **Qué SÍ aportaría** | Un instrumento de TERCERO —de los dos orígenes independientes de nuestra taxonomía—, con ~1.200 hechos regulatorios por economía, para cuatro ejes vivos |
| **Acción recomendada** | Esperar la edición 2026 con una vigilancia automática. Este documento deja decidido de antemano qué cruzaríamos, para no decidirlo con prisa el día que salga |

---

## 1. La cobertura, que es lo que decide

La edición 2025 es **interina** y cubre **101 economías**. La República Dominicana **no está**.
Comprobado contra la hoja `00_B-READY_Pillar_Score`, no contra el resumen del informe.

De América Latina y el Caribe hay once:

> Barbados · Colombia · Costa Rica · Ecuador · El Salvador · Jamaica · México · Paraguay ·
> Perú · Trinidad y Tobago · Uruguay

La edición 2024 cubría 50 economías. La progresión 50 → 101 → «cobertura global ampliada»
hace probable que el país entre en 2026, pero **el emisor no lo dice** y esto no se registra
como un hecho: se registra como lo que es, una expectativa.

---

## 2. Por qué no sustituye a los índices muertos de la END 2030

Cinco indicadores de la Ley 1-12 quedaron sin instrumento porque el WEF discontinuó lo que la
ley eligió (ver `modules/law_intel/expedientes/end_2030/campo.yaml`). La tentación es
reemplazarlos con B-READY. **No procede, por dos razones independientes.**

**Mide otra cosa.** El 1.3 es fortaleza institucional, el 3.15 infraestructura y el 3.9
competitividad general. B-READY mide **regulación de negocios** en diez temas acotados:
entrada, ubicación, servicios, laboral, financiero, comercio, impuestos, disputas, competencia
e insolvencia. Un solapamiento parcial no es identidad de concepto.

**Y está en otra escala.** B-READY puntúa 0-100; las líneas base de la ley están en el rango
1-7 del instrumento anterior, sin puente publicado. Sustituir uno por otro sería exactamente
el error que el expediente ya rechazó con los puntajes del LLECE y con el índice de percepción
de la corrupción: construir la conversión por cuenta propia.

---

## 3. Qué aportaría de verdad

### 3.1 Es evidencia INDEPENDIENTE, que es lo que más escasea

Sus datos vienen de consultas a expertos y encuestas a empresas — `instrumento_de_tercero` en
nuestra taxonomía de verificabilidad, uno de los dos orígenes que NO dependen de que el
evaluado se califique a sí mismo. Hoy **un solo indicador medido** de la END se apoya en una
medición de tercero. Es la escasez estructural del informe, no un detalle.

### 3.2 Su ESTRUCTURA respalda cómo está armado el eje de leyes

Cada tema se abre en tres pilares:

| pilar | qué mide | equivalente nuestro |
|---|---|---|
| 1 · Marco regulatorio | si la norma existe y qué dice | que la obligación EXISTA |
| 2 · Servicios públicos | si el Estado provee lo que la norma promete | que se CUMPLA |
| 3 · Eficiencia operativa | qué experimentan las empresas | el desenlace |

Es la misma distinción que el módulo de leyes hace entre una obligación asentada y una
cumplida. Que un organismo internacional haya llegado a ella de forma independiente es
respaldo conceptual citable, y vale aunque nunca se integre el dato.

### 3.3 Cuatro temas tocan ejes vivos

| tema de B-READY | eje nuestro | qué aportaría |
|---|---|---|
| `05_Financial_Services` | `banking` | calidad regulatoria del crédito comercial, debida diligencia, registro de garantías |
| `10_Business_Insolvency` | `banking` (propensión a quiebra) | estándares del proceso concursal — el marco en el que ocurren las terminaciones que ya registramos |
| `07_Taxation` | `macro` · indicador 3.25 de la END | administración tributaria, distinto de la presión tributaria que ya medimos |
| `06_International_Trade` | `trade` · indicadores 3.18-3.20 | fricción regulatoria del comercio, al lado de la cuota de mercado que ya computamos |

---

## 4. ¿Discrimina? Medido contra los once pares de la región

Un instrumento sirve si separa. Puntajes generales por tema de las once economías de la
región, edición 2025:

| tema | mín | mediana | máx | rango | extremos |
|---|---:|---:|---:|---:|---|
| Business Entry | 45,9 | 67,4 | 85,4 | 39,5 | Colombia / El Salvador |
| Business Location | 43,4 | 61,2 | 72,1 | 28,7 | Costa Rica / Trinidad y Tobago |
| Utility Services | 62,9 | 71,4 | 87,7 | 24,8 | Colombia / Jamaica |
| Labor | 57,6 | 64,0 | 69,6 | **12,0** | Perú / Uruguay |
| Financial Services | 63,5 | 74,4 | 83,5 | 20,1 | México / Ecuador |
| International Trade | 42,4 | 56,7 | 65,2 | 22,8 | México / Trinidad y Tobago |
| Taxation | 24,9 | 51,8 | 63,5 | 38,6 | México / Trinidad y Tobago |
| Dispute Resolution | 42,0 | 51,1 | 66,0 | 23,9 | Colombia / Trinidad y Tobago |
| Market Competition | 41,5 | 53,1 | 67,4 | 25,9 | Perú / Jamaica |
| **Business Insolvency** | 7,7 | 51,7 | 73,3 | **65,6** | Colombia / El Salvador |

**Lo que esto dice, y conviene tenerlo decidido antes de que salga el dato:**

- **Insolvencia separa como ningún otro** —65,6 puntos entre el mejor y el peor de la
  región—, y es justo el tema que toca el trabajo de propensión a quiebra. Es el primer
  candidato a cruzar.
- **Laboral casi no separa** (12,0 puntos entre once países). Un eje con esa dispersión no
  ordena: aporta descripción, no ranking. Conviene saberlo de antemano para no prometerlo.
- Tributación e ingreso de empresas también separan bien y son los siguientes.

---

## 5. Qué hacer

1. **No construir nada hoy.** No hay dato del país que integrar.
2. **Vigilar la edición 2026** de forma automática, contra la página de publicaciones del
   emisor, en vez de acordarse.
3. **El día que el país entre**, empezar por insolvencia contra el eje de banca, que es donde
   el instrumento más separa y donde tenemos un trabajo abierto que lo puede usar.
4. **Nunca** usarlo para tapar los indicadores muertos de la END. Que un instrumento nuevo
   exista no vuelve medible una meta fijada sobre otro.
