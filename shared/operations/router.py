"""Platform-wide Operation Console endpoints (cross-module).

prefix: /api/v1/operations
Serves every operation any module registered via ``register_operation``.
"""
from datetime import date
from typing import Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User, UserRole, role_satisfies
from shared.database.session import get_db
from shared.operations import service as ops

router = APIRouter()


def _require_admin(user: User) -> None:
    # Jerárquico: super_admin ⊇ admin (un chequeo plano `!= admin` dejaba afuera a
    # super_admin, que debe poder todo lo de admin).
    if not role_satisfies(user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Se requiere rol admin")


@router.get("/status", summary="Estado de todas las operaciones")
async def operations_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return ops.all_status(db)


@router.get("/validacion", summary="Frescura de la validación de cada eje")
async def validacion_frescura(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Por eje: si su cifra de validación sigue correspondiendo al insumo que la produjo.

    La consola mostraba cuándo corrió cada operación, que es una pregunta distinta —y la que
    no alcanzó—: el backtest de banca había corrido «hace tres semanas» sin nada anómalo a la
    vista, mientras el score que medía ya no era el mismo. Acá la columna es el veredicto:
    `vigente`, `obsoleto` u `obsolescencia indeterminada`.
    """
    import json

    from shared.settings.models import AppSetting
    from shared.validation.frescura import MOTORES, con_frescura

    _require_admin(current_user)
    filas = []
    for eje, motor in sorted(MOTORES.items()):
        row = db.query(AppSetting).filter(AppSetting.key == motor.clave).first()
        reporte = None
        if row and row.value:
            try:
                reporte = json.loads(str(row.value))
            except (ValueError, TypeError):
                reporte = None
        if reporte is None:
            filas.append({"eje": eje, "operacion": motor.operacion, "tiene_reporte": False,
                          "stale": None, "stale_reason": "no hay reporte persistido"})
            continue
        f = con_frescura(reporte, eje, db)
        filas.append({
            "eje": eje, "operacion": motor.operacion, "tiene_reporte": True,
            "generated_at": f.get("generated_at"),
            "stale": f.get("stale"), "stale_reason": f.get("stale_reason"),
            "stale_scope": f.get("stale_scope"),
            "disparado_por": list(motor.disparado_por),
            "sin_cascada_motivo": motor.sin_cascada_motivo,
        })
    return {"ejes": filas,
            "obsoletos": [f["eje"] for f in filas if f.get("stale") is True],
            "indeterminados": [f["eje"] for f in filas if f.get("stale") is None]}


@router.post("/{name}/run", summary="Disparar una operación")
async def run_operation(
    name: str,
    params: Optional[Dict] = Body(None, description="Parámetros (p.ej. {\"period\": \"2025-12\"})"),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return ops.trigger(name, origin="manual", user_id=current_user.id, params=params or {})


class ScheduleUpdate(BaseModel):
    enabled: bool
    interval_hours: Optional[int] = None
    params: Optional[Dict] = None


@router.put("/{name}/schedule", summary="Configurar el agendado de una operación")
async def set_operation_schedule(
    name: str,
    body: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    try:
        return ops.set_schedule(db, name, body.enabled, body.interval_hours, body.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/llm-spend", summary="Gasto del modelo por disparador, módulo y motivo")
async def llm_spend(
    desde: Optional[date] = Query(
        None, description="Fecha inicial inclusive (AAAA-MM-DD). Por defecto, 30 días atrás"),
    hasta: Optional[date] = Query(
        None, description="Fecha final INCLUSIVE del día completo. Por defecto, hoy"),
    trigger: Optional[str] = Query(
        None, description="Detalle de un disparador; sin él, el resumen agregado"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """El gasto del modelo, consultable en vez de investigable.

    El costo de cada llamada ya se calculaba y se tiraba: los logs del proveedor de
    despliegue solo conservan la versión vigente, así que la única forma de saber en qué se
    iba el dinero era mirar la consola de Anthropic antes y después de cada corrida.

    El rango va por FECHAS y no por una ventana de N días porque la pregunta real es «¿esto
    cuadra con lo que me facturaron?», y la facturación va por ciclo calendario. ``hasta``
    incluye el día completo.

    Se agrupa por DISPARADOR porque esa es la columna que responde: el módulo dice qué
    producto consumió, el disparador dice si lo pidió alguien o si una tarea agendada lo
    generó sola.
    """
    from shared.observability import spend

    _require_admin(current_user)
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=400,
                            detail="El rango está invertido: 'desde' es posterior a 'hasta'.")
    if trigger:
        return {"disparador": trigger,
                "llamadas": spend.spend_detail(db, desde=desde, hasta=hasta,
                                               trigger=trigger)}
    return spend.spend_summary(db, desde=desde, hasta=hasta)


@router.get("/marcas-del-guard", summary="Cifras que el guard numérico marcó (y sobrevivieron)")
async def marcas_del_guard(
    desde: Optional[date] = Query(
        None, description="Fecha inicial inclusive (AAAA-MM-DD). Por defecto, 30 días atrás"),
    hasta: Optional[date] = Query(
        None, description="Fecha final INCLUSIVE del día completo. Por defecto, hoy"),
    modulo: Optional[str] = Query(
        None, description="Acotar a un eje (banking_score, insurance, …)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Qué cifras marcó el guard, para que el patrón se vea antes de que lo vea un cliente.

    Una marca del guard puede ser dos cosas opuestas: una cifra INVENTADA —su razón de ser— o
    una cifra REAL dicha en otra forma, que es un falso veto y que en su variante silenciosa
    borra del informe una observación verdadera sin producir ningún error.

    Hasta acá las marcas vivían en un `logger.warning`, que no es evento de Sentry y que no
    mira nadie, y en un contador que dice cuántas fueron pero no cuáles. Los dos falsos vetos
    de agosto de 2026 se descubrieron porque el dueño los vio en pantalla: un informe roto por
    cada dato que ya estaba en la base.

    Se agrupa por CIFRA a propósito: una que se repite entre ejes y períodos es la firma de un
    falso positivo estructural; una que aparece sola es lo que el guard vino a atrapar.
    """
    from shared.observability import marcas_del_guard as mg

    _require_admin(current_user)
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=400,
                            detail="El rango está invertido: 'desde' es posterior a 'hasta'.")
    return mg.marcas_del_guard(db, desde=desde, hasta=hasta, modulo=modulo)


@router.get("/tiempos-de-narrativa",
            summary="Cuánto tarda cada sección de un informe, y armarlo entero")
async def tiempos_de_narrativa(
    desde: Optional[date] = Query(
        None, description="Fecha inicial inclusive (AAAA-MM-DD). Por defecto, 7 días atrás"),
    hasta: Optional[date] = Query(
        None, description="Fecha final INCLUSIVE del día completo. Por defecto, hoy"),
    modulo: Optional[str] = Query(None, description="Acotar a un eje o producto"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Qué sección se come el tiempo de un informe — la pregunta que no se podía contestar.

    El registro guardaba costo, tokens y caché, pero no cuánto tardaba nada, así que un
    informe que se pasaba del techo de tiempo dejaba al diagnóstico con promedios y conjeturas.
    Se intentó así el 2026-08-26 y no alcanzó.

    Las secciones se generan en PARALELO —lo exige un test estructural que barre los
    productos; hasta el 2026-09-01 un producto lo incumplía y por eso su total era la SUMA de
    sus secciones—, así que el total de un informe es aproximadamente el
    de su sección más lenta y NO la suma. Dentro de una sección el trabajo sí es serial
    —generar, juez, regenerar—, de modo que una sola con reparaciones puede consumir el
    presupuesto entero: por eso la unidad de esta consulta es la sección.
    """
    from shared.observability import tiempos_de_narrativa as tn

    _require_admin(current_user)
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=400,
                            detail="El rango está invertido: 'desde' es posterior a 'hasta'.")
    return tn.tiempos_de_narrativa(db, desde=desde, hasta=hasta, modulo=modulo)


@router.get("/barrido-del-guard",
            summary="Corre la regla del guard sobre la prosa YA generada (sin llamar al modelo)")
async def barrido_del_guard(
    sector: Optional[str] = Query(None, description="Acotar a un producto"),
    limite: int = Query(1500, ge=1, le=1500, description="Tope de informes leídos"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Encontrar el próximo falso positivo ANTES de que mate un informe.

    El 2026-08-26 se cerró la familia «un umbral prospectivo no es una cita» validándola
    contra las frases que ya habían fallado. Al día siguiente el modelo escribió «la cobertura
    PUEDE CRUZAR por debajo del 100 %» y la regla no la reconoció: mismo verbo, otra forma. El
    hallazgo costó una generación real —cien segundos y varias llamadas al modelo— y apareció
    de a uno, como los anteriores.

    `ProductReportCache` guarda el texto generado de cada informe, sin caducidad: un corpus
    real de la prosa de este producto. Barrer la regla contra ese corpus no cuesta ninguna
    llamada al modelo, y devuelve las FORMAS VERBALES con las que el modelo introduce cifras
    que la regla todavía no reconoce.

    No emite veredicto de «sin respaldo»: eso exige el contexto de la SECCIÓN, que la caché no
    guarda, y juzgar contra otro contexto es el defecto que ya costó tres informes reales.
    """
    from shared.observability import barrido_del_guard as bg

    _require_admin(current_user)
    return bg.barrido_del_guard(db, sector=sector, limite=limite)
