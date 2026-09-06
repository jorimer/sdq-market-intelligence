"""Lo que el modelo lee de este eje — y la huella que invalida la caché de narrativas.

Existe desde el alta del eje, y no después, por un defecto concreto: la huella de contexto se
busca en `AI_CONTEXT_FILES` y, si no está, cae a este archivo; si tampoco existe **devuelve la
cadena vacía**, y una huella vacía no falla ni avisa — simplemente un arreglo de lo que el
modelo lee deja de invalidar la caché y el informe sigue sirviendo el texto viejo
indefinidamente. Tres productos estuvieron así sin saberlo.

Mientras el motor no exista (T-VL-3 y T-VL-4), este contexto declara **lo que el eje NO puede
decir todavía**, que es la única afirmación honesta disponible.
"""
from typing import Any, Dict

#: Archivos cuyo contenido forma la huella del contexto de este eje. Se declara explícito
#: para que un cambio en el motor —cuando exista— invalide la caché de narrativas.
#: Rutas RELATIVAS al módulo: así las resuelven igual el ensamblador (`ruta_de_contexto`) y
#: la regla estructural del sujeto, que lee esta tupla con `ast` y la ancla a la carpeta.
#: Con rutas desde la raíz, la regla buscaba `modules/valuation/modules/valuation/...` y
#: dejaba a `products.py` fuera sin avisar.
#:
#: Este eje no usa el motor de IA, pero su informe SÍ pasa por `ProductReportCache`, que no
#: tiene TTL: lo que invalida un informe ya generado es exactamente esta lista. La prosa y
#: el panel de transacciones están porque son lo que el informe publica.
AI_CONTEXT_FILES = (
    "ai_context.py",
    "products.py",
    "narrativa.py",
    "panel/transacciones.py",
    # El entorno decide qué relaciones se publican (umbral de «en línea», qué series) y el
    # cierre trae prosa propia (la relación declarada): los dos son receta del informe.
    "entorno.py",
    "responsabilidad.py",
)

#: Las advertencias que acompañan a cualquier cifra de este eje. Van al contexto y no a la
#: plantilla: servir el dato no alcanza, hay que pedirlo — una plantilla que no las pida las
#: deja fuera aunque estén disponibles.
CAVEATS = (
    "El valor es un RANGO, no un punto: el costo de capital no se observa, se estima.",
    "La beta y la prima de riesgo de mercado son supuestos de comparables, no dato "
    "dominicano observado; viajan declarados como rúbrica.",
    "Un score de solidez NO es un proxy de precio. Una entidad sólida puede destruir valor.",
    "Nada de esto es una recomendación de comprar o vender.",
)


def valuation_ai_context(resultado: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """El contexto compacto que se le pasa al modelo.

    Sin motor devuelve la declaración de ausencia, no un esqueleto con ceros: un motor sin su
    entrada no falla, DESAPARECE — y evaluar contra un diccionario vacío produce prosa que
    describe una entidad que nadie midió.
    """
    if not resultado:
        return {
            "estado": "sin_motor",
            "que_falta": ("el costo de capital (Ke) y el modelo de Excess Return; el eje está "
                          "dado de alta para fijar su contrato, no para entregar"),
            "caveats": list(CAVEATS),
        }
    return {"estado": "operativo", **resultado, "caveats": list(CAVEATS)}
