"""JurisAI — verificación normativa: ¿se dictó la norma, cuándo, y sigue vigente?

Es la fuente que convierte obligaciones declaradas a mano en hechos con fecha. El eje de
evaluación de leyes modela siete obligaciones de la Ley 1-12 y dos están trabadas en
`sin_registro_publico` — que NO afirma incumplimiento, solo dice que no se encontró rastro.

**La regla que gobierna este cliente.** «No encontrado» y «no existe» son cosas distintas y
solo la segunda se puede publicar. El destinatario del informe suele ser el órgano al que la
obligación le corresponde: decirle al Congreso que su comisión nunca se constituyó, con la
evidencia de «no lo encontramos», es refutable con un solo documento.

Por eso :func:`buscar` **exige el rango de fechas**. El emisor lo declaró explícitamente:
sin `desde` y `hasta`, `alcance.vacio_es_concluyente` sale siempre ``false`` porque el
alcance se calcula desde 1900 y declara el hueco. Un rango explícito es lo único que
convierte una respuesta vacía en evidencia publicable, así que acá es obligatorio y no
opcional — un parámetro opcional que decide si podés acusar a alguien se olvida.

**Dos estados que no son el mismo y viajan por separado**: ``estado_a_fecha`` es a la fecha
consultada y ``estado_vigencia`` es el de hoy. Una obligación cumplida en 2014 con un
reglamento derogado en 2019 no está cumplida hoy, y confundirlos publica lo contrario.

**Fragilidad declarada.** La URL base la generó Railway y no es un dominio propio de
JurisAI. Si el servicio se muda, este conector se rompe — por eso la base se configura desde
la pantalla de Configuración (proveedor ``jurisai``) y no vive incrustada acá.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sdq.data.jurisai")

PROVIDER = "jurisai"
SOURCE = "JurisAI"

#: Tipos de norma que el API acepta. Conjunto CERRADO: un tipo inventado devolvería vacío y
#: ese vacío se leería como «no se dictó», que es la afirmación más cara del producto.
TIPOS = frozenset({"ley", "decreto", "reglamento", "resolucion", "constitucion"})


class JurisAIUnavailable(RuntimeError):
    """No se pudo consultar. Lleva el motivo — nunca se traduce a «no existe»."""


class JurisAICredencial(JurisAIUnavailable):
    """401. El emisor NO distingue entre clave inválida, revocada o sin permiso, y hace
    bien: a quien está fuera no le corresponde saber qué parte acertó. Se propaga igual de
    indistinta en vez de adivinar cuál de las tres fue."""


def _pedir(base: str, ruta: str, clave: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if not base:
        raise JurisAIUnavailable("falta la URL base de JurisAI (Configuración → jurisai)")
    if not clave:
        raise JurisAIUnavailable("falta la clave de JurisAI (Configuración → jurisai)")
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{base.rstrip('/')}{ruta}" + (f"?{q}" if q else "")
    # `Bearer ` delante es obligatorio: sin el prefijo el emisor devuelve 401
    # `credencial_ausente`, que se leería como clave equivocada.
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {clave}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:                       # type: ignore[attr-defined]
        if e.code == 401:
            raise JurisAICredencial(
                "JurisAI rechazó la credencial (401). El emisor no distingue entre clave "
                "inválida, revocada o sin permiso.")
        raise JurisAIUnavailable(f"JurisAI respondió {e.code} en {ruta}")
    except Exception as e:  # noqa: BLE001
        raise JurisAIUnavailable(f"no se pudo consultar JurisAI ({type(e).__name__}: {e})")


def buscar(base: str, clave: str, *, desde: str, hasta: str,
           cita_a: Optional[str] = None, tipo: Optional[str] = None,
           numero: Optional[str] = None, vence: Optional[str] = None,
           limite: Optional[int] = None) -> Dict[str, Any]:
    """Busca normas. **`desde` y `hasta` son obligatorios, y no por prolijidad.**

    Sin ellos el emisor calcula el alcance desde 1900 y devuelve
    `alcance.vacio_es_concluyente = false` siempre — con lo cual una respuesta vacía no
    autoriza a escribir «no se dictó», que es justamente para lo que se consulta.
    """
    if not desde or not hasta:
        raise JurisAIUnavailable(
            "`desde` y `hasta` son obligatorios: sin rango explícito el alcance no es "
            "concluyente y un resultado vacío no se puede publicar como incumplimiento.")
    if tipo is not None and tipo not in TIPOS:
        raise JurisAIUnavailable(
            f"tipo '{tipo}' fuera del conjunto admitido {sorted(TIPOS)}; un tipo inventado "
            "devuelve vacío y ese vacío se leería como «no se dictó».")
    return _pedir(base, "/normas", clave, {
        "desde": desde, "hasta": hasta, "cita_a": cita_a, "tipo": tipo,
        "numero": numero, "vence": vence, "limite": limite})


def obtener(base: str, clave: str, norma_id: str,
            as_of: Optional[str] = None) -> Dict[str, Any]:
    """Trae una norma por su id canónico (`do:decreto:134-14`).

    `as_of` importa para reproducir un informe viejo: su veredicto se emitió con el estado
    de vigencia de entonces, y sin fijarlo cada revisión del corpus lo vuelve irreproducible.
    """
    return _pedir(base, f"/normas/{urllib.parse.quote(norma_id, safe=':')}", clave,
                  {"as_of": as_of})


def vacio_es_concluyente(respuesta: Dict[str, Any]) -> bool:
    """¿Una lista vacía autoriza a afirmar que la norma NO se dictó?

    Se lee del `alcance` que declara el emisor y NUNCA se asume. Es la única puerta entre
    `sin_registro_publico` —que no acusa a nadie— e `incumplida`, que sí.
    """
    return bool((respuesta.get("alcance") or {}).get("vacio_es_concluyente"))


def normas(respuesta: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(respuesta.get("resultados") or [])
