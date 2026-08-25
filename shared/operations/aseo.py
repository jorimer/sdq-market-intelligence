"""Aseo de los directorios de salida: que `data/` deje de crecer sin techo.

El 2026-08-25 el disco de la máquina de desarrollo llegó al 94% con 1,1 GB libres, y la
mitad del problema estaba acá: **6.313 gráficos y 9.197 informes acumulados desde marzo**,
2,7 GB y 1,2 GB, que nadie barre nunca. A ese ritmo son ~5 GB al año. Barrerlo a mano no
evita la próxima vez.

**Los gráficos son basura por construcción, y eso se comprobó antes de borrar uno.** El
generador escribe el PNG, lo EMBEBE en el PDF en la línea siguiente y no vuelve a mirarlo;
ninguna tabla guarda su ruta, ninguna ruta de la API los sirve, y el nombre lleva timestamp
así que cada informe genera el suyo. Son temporales que nunca se limpiaron.

**Los informes NO son basura, y ahí está el guard que importa.** El store durable es
`file_blob` —los bytes en Postgres, que sobreviven a un redespliegue del disco efímero— pero
hay informes anteriores al blob que solo tienen `file_path`, y la descarga cae a ese archivo.
Medido en dev: de 2 informes, 1 depende del archivo en disco. Un barrido por fecha sin mirar
la base lo habría roto.

Por eso el aseo **pregunta antes de borrar**: todo archivo referenciado por un informe sin
blob queda protegido, tenga la edad que tenga. Se protege por REFERENCIA, no por antigüedad,
porque la antigüedad no dice nada sobre si alguien lo necesita.

**Y no barre lo que no declaró.** El directorio se resuelve, se comprueba que esté DENTRO de
la raíz de datos configurada y que su nombre sea uno de los declarados. Sin eso, un
`REPORTS_DIR` mal seteado convierte una tarea de limpieza en una que borra otra cosa — y una
tarea de aseo es el peor lugar del sistema para tener un error de ruta.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

logger = logging.getLogger("sdq.operations.aseo")

#: Cuántos días se conserva cada clase de salida, y por qué esa ventana.
#:
#: Los gráficos se consumen en la misma llamada que los crea: un día bastaría. Se dejan siete
#: por si alguien quiere abrir el PNG suelto de un informe reciente para revisarlo.
#:
#: Los informes se conservan bastante más: aunque el blob los haga reproducibles, un PDF ya
#: entregado a un cliente es lo último que uno quiere tener que regenerar con prisa.
RETENCION_DIAS = {
    "charts": 7,
    "reports": 90,
}

#: Qué extensiones se barren en cada directorio. Es una lista blanca a propósito: si algún
#: día alguien deja un `.sqlite` o un `.csv` de trabajo ahí, el aseo NO lo toca. Una tarea
#: que borra «todo lo viejo» borra lo que no sabía que había.
EXTENSIONES = {
    "charts": (".png", ".jpg", ".jpeg", ".svg"),
    "reports": (".pdf", ".docx"),
}

#: La raíz bajo la cual tiene que caer todo directorio a barrer. Un `REPORTS_DIR` mal seteado
#: —a `/`, al home, a la raíz del repo— convierte esto en otra cosa, y una tarea de aseo es
#: el peor lugar del sistema para un error de ruta.
RAIZ_DE_DATOS = "data"

#: Piso de seguridad: nunca se barre un directorio con menos de esta profundidad de ruta.
_MINIMA_PROFUNDIDAD = 2


class AseoError(RuntimeError):
    """No se pudo barrer con seguridad. NUNCA se degrada a barrer igual."""


@dataclass(frozen=True)
class Barrido:
    """Lo que el aseo hizo —o haría— en un directorio."""

    directorio: str
    clase: str
    retencion_dias: int
    examinados: int
    borrados: int
    bytes_liberados: int
    protegidos_por_referencia: int
    simulacro: bool

    @property
    def mb_liberados(self) -> float:
        return round(self.bytes_liberados / (1024 * 1024), 1)


def _validar_directorio(directorio: Path, clase: str) -> Path:
    """El directorio existe, cae bajo la raíz de datos y tiene profundidad suficiente."""
    ruta = directorio.expanduser().resolve()
    if not ruta.is_dir():
        raise AseoError(f"«{ruta}» no es un directorio: no se barre lo que no se pudo mirar")
    if len(ruta.parts) < _MINIMA_PROFUNDIDAD + 1:
        raise AseoError(
            f"«{ruta}» está demasiado arriba en el árbol para ser un directorio de salida. "
            f"Un error de ruta en una tarea de aseo no se recupera.")
    if RAIZ_DE_DATOS not in ruta.parts:
        raise AseoError(
            f"«{ruta}» no cae bajo «{RAIZ_DE_DATOS}/». El aseo solo barre directorios de "
            f"salida declarados, no cualquier ruta que le pasen.")
    if clase not in RETENCION_DIAS:
        raise AseoError(f"clase «{clase}» sin retención declarada: {sorted(RETENCION_DIAS)}")
    return ruta


def archivos_protegidos(db: Any) -> Set[str]:
    """Rutas que NO se borran porque un informe sin blob todavía las necesita.

    Se protege por REFERENCIA y no por antigüedad: la edad de un archivo no dice nada sobre
    si alguien lo necesita, y el informe que depende del disco puede ser el más viejo de
    todos. Medido en dev el 2026-08-25: de 2 informes, 1 dependía del archivo.

    Si la consulta falla —tabla ausente, base sin migrar—, se levanta en vez de devolver un
    conjunto vacío: un «no hay protegidos» falso es exactamente cómo se borra lo que hacía
    falta.
    """
    if db is None:
        raise AseoError(
            "sin sesión de base no se puede saber qué informes dependen del disco, y "
            "barrer a ciegas rompería el que dependa")
    from modules.banking_score.models.models import Report

    filas = (db.query(Report.file_path)
             .filter(Report.file_blob.is_(None), Report.file_path.isnot(None))
             .all())
    protegidos: Set[str] = set()
    for (ruta,) in filas:
        if ruta:
            protegidos.add(str(Path(ruta).expanduser().resolve()))
    return protegidos


def barrer(directorio: str, clase: str, protegidos: Optional[Set[str]] = None,
           dias: Optional[int] = None, simulacro: bool = False,
           ahora: Optional[float] = None) -> Barrido:
    """Borra los archivos de `clase` más viejos que la retención, salvo los protegidos.

    `simulacro=True` cuenta sin borrar — es como se comprueba una tarea destructiva antes de
    dejarla suelta, y la operación del console lo expone como parámetro.
    """
    ruta = _validar_directorio(Path(directorio), clase)
    retencion = RETENCION_DIAS[clase] if dias is None else int(dias)
    if retencion < 1:
        raise AseoError(
            f"retención de {retencion} días: una ventana de cero borraría lo que se acaba "
            f"de generar, incluida la salida de la corrida en curso")
    corte = (ahora if ahora is not None else time.time()) - retencion * 86400
    prot = protegidos or set()
    extensiones = EXTENSIONES[clase]

    examinados = borrados = liberados = saltados = 0
    for hijo in ruta.iterdir():
        if not hijo.is_file() or hijo.suffix.lower() not in extensiones:
            continue
        examinados += 1
        try:
            st = hijo.stat()
        except OSError:                                   # pragma: no cover - carrera
            continue
        if st.st_mtime >= corte:
            continue
        if str(hijo.resolve()) in prot:
            saltados += 1
            continue
        if not simulacro:
            try:
                hijo.unlink()
            except OSError as e:                          # pragma: no cover - permisos
                logger.info("[aseo] no se pudo borrar %s: %s", hijo, e)
                continue
        borrados += 1
        liberados += st.st_size

    return Barrido(directorio=str(ruta), clase=clase, retencion_dias=retencion,
                   examinados=examinados, borrados=borrados, bytes_liberados=liberados,
                   protegidos_por_referencia=saltados, simulacro=simulacro)


def directorios_declarados() -> Dict[str, str]:
    """`{clase: ruta}` desde la configuración, sin inventar ninguna."""
    from shared.config.settings import settings

    return {"charts": settings.CHARTS_DIR, "reports": settings.REPORTS_DIR}


def run_aseo(simulacro: bool = False, db: Any = None,
             progreso: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Barre los directorios de salida declarados y devuelve qué hizo en cada uno."""
    avisar = progreso or (lambda _m: None)
    prot = archivos_protegidos(db)
    if prot:
        avisar(f"{len(prot)} archivo(s) protegido(s): informes que solo viven en disco")

    barridos: List[Barrido] = []
    for clase, ruta in directorios_declarados().items():
        if not Path(ruta).expanduser().is_dir():
            avisar(f"{clase}: «{ruta}» no existe todavía; nada que barrer")
            continue
        b = barrer(ruta, clase, protegidos=prot, simulacro=simulacro)
        barridos.append(b)
        avisar(f"{clase}: {b.borrados} de {b.examinados} · {b.mb_liberados} MB · "
               f"retención {b.retencion_dias} d"
               + (f" · {b.protegidos_por_referencia} protegidos" if b.protegidos_por_referencia
                  else ""))

    total_mb = round(sum(b.bytes_liberados for b in barridos) / (1024 * 1024), 1)
    logger.info("[aseo] %s: %s MB en %d directorios",
                "simulacro" if simulacro else "barrido", total_mb, len(barridos))
    return {
        "simulacro": simulacro,
        "mb_liberados": total_mb,
        "protegidos_por_referencia": len(prot),
        "por_directorio": [
            {"clase": b.clase, "directorio": b.directorio, "retencion_dias": b.retencion_dias,
             "examinados": b.examinados, "borrados": b.borrados, "mb": b.mb_liberados,
             "protegidos": b.protegidos_por_referencia}
            for b in barridos],
        "nota": (
            "Los gráficos son temporales por construcción: se embeben en el PDF y nadie "
            "vuelve a mirarlos. Los informes NO: los que solo tienen ruta en disco —sin "
            "`file_blob`— quedan protegidos por REFERENCIA, tengan la edad que tengan."),
    }


def _libre_en_disco(ruta: str = ".") -> Optional[float]:  # pragma: no cover - so
    """GB libres, para que la operación diga si sirvió de algo."""
    try:
        st = os.statvfs(ruta)
        return round(st.f_bavail * st.f_frsize / (1024 ** 3), 1)
    except OSError:
        return None
