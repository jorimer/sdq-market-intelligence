"""Los mensajes con que un VETO de narrativa se le explica a quien pidió el informe.

Viven acá, en un punto único, porque hay DOS superficies que emiten los mismos documentos: la
ruta de productos (`shared/products/router`) y la de reportes de banca
(`modules/banking_score/api/router_reports`, que produce el SDQ Rating). Duplicar la prosa
entre ambas es la receta conocida para que una se arregle y la otra no — el mismo patrón que
dejó a esta segunda ruta con uno de los tres gates durante meses.

Y es prosa en CONSTANTE, no incrustada en el `raise`: un literal partido por ancho de línea
deja de existir como frase en el fuente, y un test que la busque falla sin motivo o pasa sin
protegerte.

Los tres vetos se explican distinto porque son problemas distintos:

- **degradado**: el servicio de análisis no respondió. Transitorio, reintentar sirve.
- **cifra sin respaldo**: el texto afirmó un número que el dato no sostiene.
- **relación invertida**: el texto afirmó una comparación en sentido contrario al dato, y la
  sostuvo después de que se le entregara la lectura correcta.

En los tres, el veto se LISTA: un veto mudo se lee como que el informe no existía.
"""
from __future__ import annotations

from typing import Any, Dict

#: Degradación transitoria del servicio de narrativa (rate-limit/outage o corte de
#: presupuesto). Un producto premium NO se entrega hueco: se responde 503 (reintento) en vez
#: de un PDF con relleno.
NARRATIVE_DEGRADED_MSG = (
    "El análisis de este informe no está disponible en este momento por un límite temporal "
    "del servicio de generación. Reintente en unos minutos."
)

#: El OTRO motivo por el que un premium no se entrega, y hasta el 2026-08-26 compartía el
#: mensaje de arriba: el ensamblado no terminó dentro de su techo de tiempo. Son causas
#: distintas con remedios distintos, y confundirlas impedía diagnosticar.
#:
#: El reintento acá NO es una espera a que el servicio se recupere: es aprovechamiento. El
#: motor cachea CADA SECCIÓN por separado en cuanto la termina, así que las que alcanzaron a
#: generarse antes del corte ya están guardadas y el intento siguiente arranca desde ahí.
#: Decirlo cambia lo que el usuario hace: reintentar sirve, y sirve enseguida.
NARRATIVE_TIEMPO_MSG = (
    "El informe no terminó de generarse dentro del tiempo disponible. Reintente ahora: las "
    "secciones que ya se generaron quedan guardadas y el siguiente intento retoma desde "
    "ahí, así que suele completarse."
)


def mensaje_de_degradacion(motivo: str) -> str:
    """El mensaje que corresponde al motivo por el que el análisis no se produjo."""
    return NARRATIVE_TIEMPO_MSG if motivo == "tiempo" else NARRATIVE_DEGRADED_MSG

SIN_RESPALDO_MSG = (
    "El informe no se entrega: una revisión automática detectó cifras que el dato servido no "
    "respalda en {n} sección(es) ({secciones}). No publicamos un número que no podemos "
    "sostener. Reintente en unos minutos —el texto se regenera— o avísenos si persiste."
)

RELACION_MSG = (
    "El informe no se entrega: en {n} sección(es) ({secciones}) el análisis afirma una "
    "comparación en sentido contrario al que muestran los datos, y la afirmación persistió "
    "después de corregirla. No publicamos un informe que se contradice a sí mismo. Reintente "
    "en unos minutos —el texto se regenera— o avísenos si persiste."
)


def mensaje_sin_respaldo(hallazgos: Dict[str, Any]) -> str:
    """Mensaje del veto por cifra sin respaldo, nombrando las secciones y las cifras."""
    partes = []
    for seccion, marcas in (hallazgos or {}).items():
        # La marca del guard es "69%: no aparece en el contexto servido"; al usuario le sirve
        # la CIFRA, no la glosa interna del detector.
        cifras = [str(m).split(":")[0].strip() for m in (marcas or []) if str(m).strip()]
        partes.append(f"{seccion}: {', '.join(cifras)}" if cifras else str(seccion))
    return SIN_RESPALDO_MSG.format(n=len(hallazgos or {}), secciones=" · ".join(partes))


def mensaje_relacion(hallazgos: Dict[str, Any]) -> str:
    """Mensaje del veto por relación invertida, nombrando las secciones."""
    return RELACION_MSG.format(
        n=len(hallazgos or {}), secciones=" · ".join(str(k) for k in (hallazgos or {})))
