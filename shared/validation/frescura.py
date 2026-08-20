"""Frescura de los reportes de validación: la HUELLA de su insumo, no el reloj.

Todo reporte de validación (Gini, Spearman, Gate E) es un artefacto PERSISTIDO que se
recalcula por cadencia. Eso deja un hueco que ya produjo el defecto: el 2026-08-07 una
recalibración cambió el ``overall_score`` de banca, el backtest tenía su próxima corrida
agendada para el 26-ago, y producción publicó durante 19 días un Gini de 0,44 calculado
con el score anterior — contra un deck que decía 0,16. Nadie lo vio porque **el sistema no
sabía que el reporte había quedado huérfano de su insumo**.

Es la misma clase de defecto que la caché de narrativas (ver `CLAUDE.md`): un artefacto
cuya invalidación no está cableada a sus entradas. La cura tiene dos mitades y hacen falta
las dos:

1. **Cascada** (``Operation.triggers``): la operación que produce el insumo dispara el
   recálculo. Es lo que evita que el reporte envejezca.
2. **Huella** (este módulo): el reporte guarda una firma de lo que lo produjo, y al LEERLO
   se compara contra la firma vigente. Es lo que evita que un reporte viejo se sirva como
   verdad cuando la cascada no corrió (deploy caído, operación en error, motor nuevo sin
   cablear).

Sin la huella, la cascada es una promesa; con la huella, es verificable en la respuesta.

**Qué NO hace este módulo.** No inventa frescura: si un eje no declara cómo se computa su
huella, o la lectura falla, el estado es ``indeterminado`` y ``stale`` es ``None`` —jamás
``False``—. "No sé de cuándo es" y "está al día" son cosas distintas, y confundirlas es
exactamente cómo se publicó el 0,44.
"""
from __future__ import annotations

import hashlib
import os
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from shared.validation.control_tamano import ControlDeTamano

# Clave donde cada reporte guarda su firma de insumo.
CAMPO_HUELLA = "input_fingerprint"


def firmar(partes: Dict[str, Any]) -> str:
    """Firma estable de las *partes* declaradas del insumo.

    Canónica (claves ordenadas) para que dos lecturas del mismo estado den la misma firma,
    y corta: es un identificador para comparar, no un resumen para leer.
    """
    canonico = json.dumps(partes, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()[:16]


_HUELLA_ARCHIVO: Dict[Tuple[str, int, int], str] = {}


def huella_archivo(path: os.PathLike | str) -> Optional[str]:
    """Firma del CONTENIDO de un archivo de insumo (fixture comiteado, doctrina YAML).

    Por contenido y no por fecha: un ``git checkout`` reescribe el ``mtime`` de todo el
    árbol, así que una huella por fecha marcaría obsoleto cada reporte después de cada
    deploy — la falsa alarma que hace que se deje de mirar la señal. Se cachea por
    (ruta, tamaño, mtime) para no releer megabytes en cada lectura de la API.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    clave = (str(path), st.st_size, st.st_mtime_ns)
    if clave not in _HUELLA_ARCHIVO:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for bloque in iter(lambda: fh.read(1 << 20), b""):
                h.update(bloque)
        _HUELLA_ARCHIVO[clave] = h.hexdigest()[:16]
    return _HUELLA_ARCHIVO[clave]


@dataclass(frozen=True)
class MotorValidacion:
    """Un motor de validación y de qué depende su cifra.

    ``partes`` computa, contra la base, el estado del insumo. Debe incluir algo que cambie
    cuando cambia el SCORE, no solo cuando llegan filas nuevas: la recalibración del 7-ago
    no agregó una sola observación (1.693/301 antes y después) y aun así invalidó el
    reporte. Un conteo y un período máximo no lo habrían detectado; una suma de scores sí.
    """

    eje: str
    operacion: str          # operación de consola que lo recalcula
    clave: str              # AppSetting donde vive el reporte persistido
    partes: Callable[[Session], Dict[str, Any]]
    # Operaciones que DEBEN dispararlo al terminar bien (``Operation.triggers``). Vacío
    # solo si el motor declara por qué no le corresponde cascada.
    disparado_por: Tuple[str, ...] = ()
    sin_cascada_motivo: Optional[str] = None
    # Insumos que la huella NO cubre (una fuente externa que se descarga en cada corrida,
    # por ejemplo). Viaja en la respuesta como ``stale_scope``: sin esto, un ``stale=False``
    # afirmaría más de lo que se verificó, que es la forma elegante del mismo defecto.
    insumo_no_cubierto: Tuple[str, ...] = ()
    # Contra qué CONTROL se lee la cifra de este motor. Obligatorio: un Gini sobre sujetos de
    # tamaños distintos no distingue «el score ordena» de «el tamaño ordena y el score lo
    # copia», y eso ya cambió el veredicto en dos motores (ver `control_tamano`).
    control_de_tamano: Optional[ControlDeTamano] = None


MOTORES: Dict[str, MotorValidacion] = {}


def registrar_motor(motor: MotorValidacion) -> MotorValidacion:
    """Registra un motor de validación. Los módulos llaman a esto al importarse."""
    MOTORES[motor.eje] = motor
    return motor


def huella_vigente(eje: str, db: Session) -> Optional[str]:
    """Firma del insumo TAL COMO ESTÁ HOY, o ``None`` si no se puede computar.

    Nunca propaga la excepción: una lectura de frescura que rompe el endpoint convierte
    una advertencia en una caída. El ``None`` viaja y se declara como indeterminado.
    """
    motor = MOTORES.get(eje)
    if motor is None:
        return None
    try:
        return firmar(motor.partes(db))
    except Exception:  # noqa: BLE001 — la frescura jamás debe tumbar la lectura
        db.rollback()
        return None


def sellar(reporte: Dict[str, Any], eje: str, db: Session) -> Dict[str, Any]:
    """Sella un reporte RECIÉN calculado con su fecha y la huella de su insumo.

    Se llama en el runner, no en la lectura: la huella que vale es la del momento del
    cálculo. Muta y devuelve el mismo dict, que es como lo usan los runners.
    """
    reporte["generated_at"] = datetime.now(timezone.utc).isoformat()
    reporte[CAMPO_HUELLA] = huella_vigente(eje, db)
    return reporte


def con_frescura(reporte: Dict[str, Any], eje: str, db: Session) -> Dict[str, Any]:
    """Devuelve el reporte con su veredicto de frescura: ``stale`` + ``stale_reason``.

    Tres estados, y el tercero no es un detalle:

    - ``stale=False`` — la huella del reporte coincide con la del insumo de hoy.
    - ``stale=True``  — el insumo cambió después del cálculo: la cifra es de otro mundo.
    - ``stale=None``  — indeterminado (reporte sin sellar, eje sin huella declarada, o la
      lectura del insumo falló). No es "está bien": es "no se sabe", y el gate de
      publicación lo trata como no publicable.
    """
    vigente = huella_vigente(eje, db)
    delreporte = reporte.get(CAMPO_HUELLA)
    motor = MOTORES.get(eje)

    if motor is None:
        estado, motivo = None, "eje sin motor de validación declarado"
    elif delreporte is None:
        estado, motivo = None, "reporte sin huella de insumo (anterior a la huella o sin sellar)"
    elif vigente is None:
        estado, motivo = None, "no se pudo computar la huella del insumo vigente"
    elif vigente == delreporte:
        estado, motivo = False, None
    else:
        estado, motivo = True, "el insumo cambió después de calcular el reporte"

    reporte["stale"] = estado
    reporte["stale_reason"] = motivo
    if motor is not None and motor.insumo_no_cubierto:
        reporte["stale_scope"] = list(motor.insumo_no_cubierto)
    return reporte


def es_publicable(reporte: Dict[str, Any]) -> bool:
    """¿Esta cifra puede entrar a material publicado?

    Solo si se verificó vigente. El indeterminado NO pasa: la mitad de este problema fue
    servir como verdad un número del que nadie podía decir de cuándo era.
    """
    return reporte.get("stale") is False
