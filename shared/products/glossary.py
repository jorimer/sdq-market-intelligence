"""Glosario automático de siglas y términos técnicos para los reportes.

Los reportes SDQ·MIP los lee una audiencia mixta (técnica + ejecutiva). El cuerpo del
texto conserva el vocabulario técnico que cada audiencia maneja (doctrina de voz en
``shared/narrative/cerebro.py``); este módulo cubre la definición de diccionario: detecta
qué términos del catálogo aparecen en el texto YA REDACTADO de un reporte y produce la
sección "Glosario" solo con esos — nunca un volcado completo del catálogo.

Detección conservadora: borde de palabra en los extremos alfanuméricos del término y
case-sensitive para siglas en mayúsculas (evita que un "one" inglés dispare la entrada
de la ONE). Sin dependencias del motor de narrativa — es un diccionario estático.
"""
from __future__ import annotations

import re
from typing import Dict

# Término tal como aparece en el texto → definición de una frase, en español llano,
# sin usar el término dentro de su propia definición. Agrupado por categoría; el orden
# de definición es el orden en que se listan en la sección Glosario.
GLOSSARY: Dict[str, str] = {
    # ── Índices propios de SDQ ──────────────────────────────────────────
    "ISF": "índice propio de SDQ que resume la solidez financiera de una entidad "
           "combinando capital, calidad de activos, eficiencia, liquidez y diversificación",
    "ISA": "índice propio de SDQ que califica la solidez de una administradora de fondos "
           "de pensiones a partir de sus estados financieros auditados",
    "ITT": "índice propio de SDQ que sintetiza el pulso del sector turístico "
           "(llegadas de visitantes y señales asociadas)",
    "IRMP": "índice propio de SDQ que mide el riesgo macro-político del país "
            "(gobernabilidad, volatilidad regulatoria e incertidumbre electoral)",
    "IAI": "índice propio de SDQ que mide el atractivo de invertir en un sector "
           "(demanda, capital humano, entorno y desempeño)",
    "IRC": "índice propio de SDQ que mide la resiliencia climática nacional "
           "(exposición, vulnerabilidad y capacidad de respuesta)",
    "IDM": "índice propio de SDQ que resume el desarrollo del mercado laboral y social "
           "(informalidad, ingresos y empleo)",
    # ── Indicadores oficiales / macro ───────────────────────────────────
    "TPM": "tasa de política monetaria: la tasa de interés de referencia que fija el "
           "banco central y que ancla el costo del dinero en la economía",
    "IMAE": "indicador mensual de actividad económica: aproximación de alta frecuencia "
            "al crecimiento del país que publica el banco central",
    "VAB": "valor agregado bruto: el aporte de un sector a la producción del país, "
           "descontando los insumos que consume",
    "IPC": "índice de precios al consumidor: la medida oficial de inflación sobre la "
           "canasta de consumo de los hogares",
    "WGI": "indicadores de gobernabilidad del Banco Mundial (estado de derecho, control "
           "de corrupción, efectividad del gobierno, entre otros), en percentiles de 0 a 100",
    "GDELT": "base global de eventos extraída de medios de comunicación, usada para medir "
             "tono e inestabilidad política en tiempo casi real",
    # ── Instituciones / fuentes ─────────────────────────────────────────
    "BCRD": "Banco Central de la República Dominicana",
    "SIB": "Superintendencia de Bancos de la República Dominicana",
    "SIPEN": "Superintendencia de Pensiones de la República Dominicana",
    "SIS": "Superintendencia de Seguros de la República Dominicana",
    "SIMBAD": "sistema público de estadísticas de la Superintendencia de Bancos",
    "ONE": "Oficina Nacional de Estadística de la República Dominicana",
    "DGII": "Dirección General de Impuestos Internos, la autoridad tributaria dominicana",
    "DGA": "Dirección General de Aduanas de la República Dominicana",
    "DIGEPRES": "Dirección General de Presupuesto del gobierno dominicano",
    # ── Métricas financieras / bancarias ────────────────────────────────
    "ROA": "rentabilidad sobre activos: cuánta ganancia genera la entidad por cada peso "
           "de activos que administra",
    "ROE": "rentabilidad sobre patrimonio: cuánta ganancia genera la entidad por cada "
           "peso que los accionistas tienen invertido",
    "ICAP": "índice de capitalización: el colchón de capital de la entidad frente a sus "
            "riesgos; el mínimo regulatorio dominicano es 10%",
    "Tier 1": "capital de máxima calidad de una entidad (acciones y utilidades retenidas), "
              "el primero en absorber pérdidas",
    "CR5": "porción del mercado concentrada en las 5 entidades más grandes",
    "CR10": "porción del mercado concentrada en las 10 entidades más grandes",
    "RevPAR": "ingreso por habitación disponible: la métrica estándar de desempeño "
              "hotelero (tarifa lograda combinada con ocupación)",
    "HHI": "índice que mide qué tan concentrado está un mercado; por encima de 2,500 "
           "se considera altamente concentrado",
    "CAGR": "tasa de crecimiento anual compuesta: el ritmo promedio al que algo creció "
            "por año en un período dado",
    "NAV": "valor del fondo por cuota: el precio unitario al que se valora la "
           "participación en un fondo de inversión o pensiones",
    "Sharpe": "medida de retorno ajustado por riesgo: cuánto rinde una inversión por "
              "cada unidad de volatilidad que asume",
    # ── Estadística / validación de modelos ─────────────────────────────
    "Gini": "medida de desigualdad o de poder discriminante entre 0 y 1; en validación "
            "de modelos, más alto significa que el modelo separa mejor los casos",
    "macro-F1": "medida de acierto de un modelo de clasificación que promedia el "
                "desempeño en todas las categorías por igual, sin favorecer a la mayoritaria",
    "XGBoost": "algoritmo de aprendizaje automático basado en árboles de decisión, "
               "estándar de industria para predicción con datos tabulares",
    "backtest": "prueba de un modelo contra el pasado: se simula qué habría predicho "
                "con los datos de entonces y se compara con lo que realmente ocurrió",
    "out-of-sample": "evaluado sobre datos que el modelo nunca vio durante su "
                     "entrenamiento — la prueba honesta de su capacidad real",
    "IC 90%": "intervalo de confianza al 90%: el rango dentro del cual se espera que "
              "caiga el valor real en 9 de cada 10 ocasiones",
    # ── Unidades ────────────────────────────────────────────────────────
    "pp": "puntos porcentuales: la diferencia absoluta entre dos porcentajes "
          "(de 5% a 7% son 2 puntos porcentuales)",
    "pb": "puntos básicos: centésimas de punto porcentual (100 puntos básicos = 1%)",
}


def _term_pattern(term: str) -> re.Pattern:
    """Patrón de detección para *term* en un texto redactado.

    Borde de palabra (``\\b``) en cada extremo SOLO si ese extremo es alfanumérico —
    el '%' de "IC 90%" no lleva ``\\b`` (entre '%' y un espacio no hay frontera de
    palabra y el patrón nunca calzaría). Case-SENSITIVE si el término es todo
    mayúsculas (siglas: ISF, ROA, ONE — evita que un "one" cualquiera dispare la
    entrada) o si es una unidad corta (≤2 letras: pp, pb — evita que un "PP"/"PB"
    en mayúsculas, p.ej. unas siglas ajenas al catálogo, dispare la unidad);
    case-INSENSITIVE para el resto (backtest, Gini — para calzar aunque el texto lo
    capitalice distinto, p.ej. al inicio de una oración)."""
    pat = re.escape(term)
    if term and (term[0].isalnum() or term[0] == "_"):
        pat = r"\b" + pat
    if term and (term[-1].isalnum() or term[-1] == "_"):
        pat = pat + r"\b"
    flags = 0 if (term.isupper() or len(term) <= 2) else re.IGNORECASE
    return re.compile(pat, flags)


def glossary_markdown(text: str) -> str:
    """Markdown de la sección Glosario: ``- **term** — definición`` SOLO para los
    términos de ``GLOSSARY`` que aparecen en *text*, en el orden del catálogo.
    Cadena vacía si ningún término calza — el llamador nunca debe imprimir un
    glosario vacío."""
    if not text:
        return ""
    lines = [f"- **{term}** — {definition}"
             for term, definition in GLOSSARY.items()
             if _term_pattern(term).search(text)]
    return "\n".join(lines)
