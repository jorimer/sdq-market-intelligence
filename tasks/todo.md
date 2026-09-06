# El informe de valuación contra la estructura pedida — plan de los tres cierres

## Lo que se midió (Deep Dive real generado de `d9578841`, el head del #1138)

El informe trae 13 secciones. Contra la estructura de diez que se pidió, siete están, tres
faltan o están a medias, y **la estructura pedida no estaba escrita en ningún lugar del repo**
(0 coincidencias en `tasks/`, `docs/`, `modules/valuation/`, `shared/products/`): el eje se
diseñó con el spread ROE − Ke como columna y nadie cruzó las dos listas.

| Pedido | Estado | Evidencia |
|---|---|---|
| 4 · Análisis macro e industria | **falta** | 3 líneas macro incidentales; el PIB solo en Fuentes |
| 7 · Cálculos y ajustes | **a medias** | Ke y sensibilidad sí; **0 líneas** sobre prima de control, minoría o iliquidez (DLOM): ni aplicados ni declarados |
| 9 · Conclusión y firma | **a medias** | §7 Conclusión existe; ninguna firma, certificación ni declaración de responsabilidad (los 7 hits de «firma\|certific» eran «afirmar»/«confirmado») |

Lo demás —portada, resumen, entidad, financiero, metodología, supuestos + limitaciones,
anexo del panel— está. Queda FUERA de este plan el anexo de planillas del modelo (series por
fecha, insumos del Ke, tabla de la regresión P/B): es la cuarta brecha y se abre aparte.

## Doctrina que gobierna los tres

- **Prosa computada, no IA.** El eje entero es `prosa_computada=True`; las tres secciones
  nuevas salen de `_secciones_computadas()` —el ÚNICO constructor, que también alimenta la
  muestra— o la muestra dirá algo que el informe no dice.
- **Un tipo nuevo se registra en TODAS sus superficies**: `SECCION_*`, `_SECTION_TITLES`,
  el manifiesto (insight Y deep dive), `_secciones_computadas`, y
  `test_el_informe_esta_completo.py`. Falta una y la sección desaparece sin fallar.
- **Se pide por HTTP.** El test de cada cierre entra por `GET /api/v1/products/valuation/
  deep_dive/report` (el patrón de `test_el_panel_llega_al_informe.py`), no por la función de prosa.
- **Correr el test contra el código VIEJO antes de arreglar** (mis tests nacen ciegos).
- **La doctrina gobierna el dato, no el texto**: la afirmación de método va UNA vez y dice
  de qué está hecho el valor; no se enumera lo que falta.

---

## Cierre 0 (apareció midiendo) · El ROE es de DOCE meses — HECHO

Rama `claude/vl-9-roe-doce-meses`, apilada sobre el cierre 2. `historia_de` dividía la utilidad
ACUMULADA del ejercicio por el patrimonio del corte anterior; con cortes trimestrales el ROE
proyectado salía a ~60 % del real y el veredicto de creación de valor se invertía. Ahora: ventana
de doce meses (la de `banking_score/scoring/ttm.py`) sobre el patrimonio de doce meses antes;
un corte sin utilidad no vale cero; el selector ofrece solo entidades con ventana. Fixtures con
cortes trimestrales en los cuatro archivos que valúan; tres exentos con motivo. **Cambia toda
valuación real en prod** (decisión del dueño 2026-09-06: arreglar primero).

## Cierre 1 · Macro e industria (`SECCION_ENTORNO = "entorno_macro_e_industria"`) — HECHO

Rama `claude/vl-10-entorno-macro-e-industria`, apilada sobre el cierre 0. Dos cambios respecto
del plan: (a) el comparador de industria es el **RESTO del tipo**, no el total — una entidad que
es el 75 % de su tipo contra el total siempre sale «en línea» (`comparar contra el resto, no
contra el total`); (b) el bloque viaja en el PAYLOAD (`entorno.a_dict`) para que la prosa no
recompute y el informe en caché diga el entorno con el que se valuó. La Rf que se cita es la de
la lectura, no una relectura de la curva.

**Va entre §3 La entidad y §4 Análisis financiero** (insight y deep dive), que es donde un
lector espera el contexto antes de los números de la entidad.

### Qué se computa (nunca se transcribe)

**Capa macro, al corte del informe**, leída con `panel.observaciones(db, code)` —el mismo
acceso que ya usa `cost_of_capital.rf_de_la_curva`— y con la MEDIDA viajando con la cifra:

| Cifra | Serie | Medida |
|---|---|---|
| PIB real, variación interanual | `bcrd.xls.pib_2018.serie_original_indice` → `panel.variacion_interanual_pct` | INTERANUAL, pp |
| Inflación 12 meses | `bcrd.xls.ipc_base_2019_2020.variacion_porcentual_12_meses` | % |
| Tipo de cambio de referencia (venta) | `bcrd.xls.tasa_dolar_referencia_mc.promtrimestral.venta` | RD$/US$, nivel + interanual |
| Tasa libre de riesgo en pesos | `SERIE_RF` (ya en el informe como insumo del Ke) | %, la misma que usa el modelo |

Cada cifra lleva su período de fuente (regla del framework: las capas agregadas se publican
con SU período, el corte manda sobre la entidad). Serie ausente → `None` y la frase se omite;
jamás 0.0.

**Capa industria, sobre `banking_data` al MISMO corte y sobre el TIPO de la entidad**
(`lec.tipo_de_entidad`, el padrón completo — como `_posicion_en_su_tipo`):

- `roe_del_tipo_pct` (utilidad / patrimonio promedio del grupo) y la RELACIÓN computada:
  «la entidad rinde X pp por encima/debajo de su tipo».
- `crecimiento_cartera_del_tipo_pct` interanual, y el de la entidad, y la relación.
- `morosidad_del_tipo_pct` (`cartera_vencida_90d / cartera_bruta`) vs la entidad.
- `cuota_patrimonio_del_tipo_pct` (ya computada en `_posicion_en_su_tipo`; se reutiliza).

Las claves nombran su población (`_del_tipo`): el SUJETO viaja con el número. Con menos de
dos entidades en el tipo, la capa se omite y se dice por qué (como hoy la posición).

### Por qué NO se usa el ledger de proyecciones acá
La proyección del PIB vive en `macro_forecast` con su propio gate y readiness. Citarla desde
valuación la publicaría por una puerta que no tiene ese gate. Si más adelante se quiere el
PIB proyectado, entra por su `emitir()` con `medida` y `admisible`, no por un `SELECT`.

### Pasos
1. Test por HTTP que exija `SECCION_ENTORNO` con las cuatro cifras macro y las tres de
   industria, con relación computada. **Correrlo contra el código actual: debe fallar.**
2. `modules/valuation/entorno.py`: `leer_entorno(db, lec) -> Entorno` (dataclass con
   `Optional` por cifra, período por cifra, medida). Sin prosa.
3. `narrativa.entorno(ent, lec)`: prosa computada; relaciones «por encima/debajo» calculadas.
4. Registro en las cinco superficies. Muestra: `_SAMPLE_PAYLOAD` gana un bloque `entorno`
   ilustrativo (la entidad ficticia no puede tener industria real).
5. Gates (tres) · PR · merge · Deep Dive real en prod (>2 s) y leer la sección.

---

## Cierre 2 · Base del valor y ajustes (control, minoría, iliquidez) — HECHO

Rama `claude/vl-8-base-del-valor`. Además de lo planeado apareció y se cerró un defecto: §6 y §10 servían el MISMO texto (`SECCION_SUPUESTOS: metodologia`); ahora §10 trae los parámetros que produjeron la cifra (viajan en el payload) y la sensibilidad. Y la muestra publicaba un Ke que el motor no puede producir; se recomputó con el motor.

Hoy el modelo valúa el **100 % del patrimonio, como negocio en marcha, sin ajustar**. Eso es
una decisión correcta para lo que el eje afirma, pero no está DICHA — y un lector profesional
la busca. El punto que además hace CONSISTENTE al informe: el panel de transacciones son
compras de control (100 % o mayoría), así que el contraste P/B modelo vs. P/B pagado ya está
en la misma base. Hoy eso no se dice y el lector no puede saberlo.

### Qué cambia (prosa en CONSTANTES, no en literales partidos)
- `narrativa.metodologia()`: un párrafo **`BASE_DEL_VALOR`** — «valor del 100 % del
  patrimonio, base de control implícita, negocio en marcha; no se aplica prima de control ni
  descuento por iliquidez; la referencia de mercado está en la misma base porque el panel
  son operaciones de control».
- `narrativa.limitaciones()`: la afirmación de método UNA vez: la cifra es para una
  participación de control; una participación minoritaria o no transferible **no vale la
  fracción proporcional**, y ese ajuste no se estima acá.
- Tipo `aap` (mutual): frase propia — no hay acciones que comprar; el valor es del negocio,
  no de un título. Ya existe el gancho (`_TIPOS`, `evidencia_del_tipo`).
- El resumen del contraste (`SECCION_CONTRASTE`) nombra la base de los múltiplos del panel.

### Pasos
1. Test por HTTP: las tres frases aparecen UNA vez cada una (no dos), y la de AAP solo para
   AAP. Contra el código actual: falla.
2. Constantes + cableado. 3. Gates · PR · merge · prod.

**Decisión del dueño, no bloqueante:** si en algún momento se va a OFRECER una valuación
de participación minoritaria (con DLOM estimado), es otro producto; este plan solo declara.

---

## Cierre 3 · Conclusión y responsabilidad (`SECCION_CIERRE = "conclusion_y_responsabilidad"`) — HECHO

Rama `claude/vl-11-conclusion-y-responsabilidad`. Decisiones del dueño (2026-09-06): firma
INSTITUCIONAL (SDQ Consulting, sin firmante personal); independencia AFIRMADA con excepción por
entidad (`settings.VALUACION_ENTIDADES_CON_RELACION`, nombres o ids separados por coma — vacío en
prod hasta que se cargue); en insight y deep dive. Todo computado: emisión = snapshot, versión =
última entrada del changelog del eje (se agregó la del ROE de doce meses, #1141, que faltaba),
validación = `validation_state()`. La muestra computa el cierre igual que el informe real.

Última sección, en insight y deep dive. **Todo computado de la plataforma**; nada escrito
a mano, porque un número o una fecha copiada se desincroniza:

- Fecha de emisión y corte (del snapshot).
- Versión de la metodología: la última entrada del changelog del eje
  (`GET /api/v1/products/methodology-changelog?sector=valuation`).
- Estado de validación: `ValuationProduct.validation_state()` — hoy «no contrastada
  contra precios pagados», computado por `contraste_del_modelo()`.
- Quién responde: `settings.VALUACION_FIRMANTE` (nombre y cargo) si está configurado; si
  no, la sección **declara** «emitido por la plataforma SDQ·MIP sin firmante individual».
  No se fabrica una firma.
- Alcance de la certificación: independencia (SDQ no tiene interés en la entidad) y que
  NO es una valuación bajo NIIF 13 ni IVS — lo que se puede afirmar y solo eso.

### Decisiones del dueño (BLOQUEAN el paso 2)
1. ¿Quién firma y con qué cargo? (`VALUACION_FIRMANTE` en el entorno de prod.)
2. ¿La declaración de independencia se afirma siempre o depende de la entidad? (si hay
   clientes de consultoría entre los bancos, hay que poder EXCEPTUAR por entidad.)
3. ¿Va en insight o solo en deep dive?

### Pasos
1. Test por HTTP: sección presente, fecha = emisión, versión = changelog, estado =
   `validation_state()`, y con `VALUACION_FIRMANTE` vacío la frase de «sin firmante».
2. (tras las decisiones) `settings` + `narrativa.cierre()` + registro en las superficies.
3. Gates · PR · merge · prod.

---

## Orden y por qué
**2 → 1 → 3.** El 2 es un PR de prosa que cierra una omisión visible en el documento que ya se
entrega; el 1 es el más largo (dato + plantilla); el 3 espera tres decisiones. Cada uno es un
PR aparte con su test por HTTP y su Deep Dive real en prod.

## Pendiente ajeno a este plan
- #1138 (M&A) en poll de merge → deploy → Deep Dive real en prod.
- `macro_forecast`: readiness 0,70 con niveles activos; MIN_OOS recalibrable. Decisión del dueño.
