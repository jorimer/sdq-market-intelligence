"""Law Intel como producto del catálogo — engancha al pipeline de informes existente.

**La huella del expediente es lo crítico de este módulo.** La caché de narrativas
(`ProductReportCache`, Postgres, SIN TTL) invalida por dato + receta + contexto declarado. En
los demás sectores el dato vive en la base, así que un arreglo mueve el payload y el informe
se regenera. Acá el dato de la ley vive en ARCHIVOS del repositorio: corregir una meta del
CSV o el estado de una obligación no movería el payload, y los informes ya generados servirían
el texto viejo indefinidamente. Por eso el snapshot incluye `expediente_fingerprint`, que
hashea los archivos del expediente — sin eso, el arreglo de una cifra queda invisible para
los clientes que ya descargaron su informe.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.law_intel.ai_context import law_ai_context, secciones_sin_dato
from modules.law_intel.registro import RAIZ, cargar, expedientes
from shared.products import (DataHealth, Granularity, ProductSnapshot, ProductTier,
                             SectorProductManifest, TierLevelSpec, ValidationState,
                             register_product)
from shared.products.render import render_product_pdf

logger = logging.getLogger("sdq.law_intel.products")

SECTOR_KEY = "law"
DISPLAY = "SDQ Evaluación de Leyes"

# Declarado para la regla del sujeto y para la huella de la caché: el contexto de este
# módulo NO vive solo en `ai_context.py` — la mitad de lo que el modelo lee sale de las
# frases ya redactadas por el motor de scoring.
AI_CONTEXT_FILES = ("ai_context.py", "scoring/accionabilidad.py", "scoring/semaforo.py")

_SECTION_TITLES = {
    "cumplimiento": "Cumplimiento de las metas",
    "coherencia_proceso": "Proceso declarado contra resultado medido",
    "brechas": "Lo que este informe no puede medir",
    "recomendaciones": "Qué se puede exigir, y con qué instrumento",
}
_SIN_DATO = ("El informe no puede pronunciarse sobre esta sección con la cobertura actual. "
             "La sección de brechas dice qué falta y a quién le corresponde producirlo.")

# Exemplar curado de la muestra. Se redacta a mano, sobre un instrumento FICTICIO, y muestra
# las cuatro cosas que distinguen a este producto: la cobertura declarada en la primera línea,
# el veredicto sin eufemismo, la brecha con responsable y la recomendación con base legal.
_SAMPLE_NARRATIVES = {
    "cumplimiento": (
        "Esta evaluación mide 12 de los 30 indicadores que la Ley 000-00 se fijó a sí misma. "
        "De los 12 medidos, 5 alcanzan su meta al corte de 2025 y 6 no la alcanzarán al ritmo "
        "actual; 1 retrocede. Los 18 restantes no se miden — que no es lo mismo que decir que "
        "se incumplen, y la sección de brechas explica por qué.\n\n"
        "El indicador que más pesa en el juicio es el de recaudación: avanza, pero a un ritmo "
        "que no llega a la meta de 2025. La ley fija cortes quinquenales y cada uno se juzga "
        "cuando le toca, así que el veredicto es contra la meta ya vencida y no contra la de "
        "2035."),
    "coherencia_proceso": (
        "El instrumento de proceso previsto por la ley reporta un cumplimiento formal alto de "
        "sus compromisos. Cuando el indicador que ese instrumento existía para mover no se "
        "mueve, las dos lecturas no pueden ser ambas satisfactorias: un alto cumplimiento de "
        "actividad con el resultado quieto es el patrón que permite reportar éxito "
        "indefinidamente mientras el indicador se deteriora. En esta muestra no se detectan "
        "contradicciones de ese tipo."),
    "brechas": (
        "De los 30 indicadores de la ley, 18 no se miden en este informe. La atribución "
        "importa: 14 son una brecha de la plataforma —falta conectar o verificar la fuente— y "
        "4 son del propio instrumento, porque la ley fija esas metas en palabras o como "
        "umbral y ninguna fuente las vuelve restables.\n\n"
        "Se declara la diferencia porque imputarle al Estado un hueco que es nuestro infla el "
        "reclamo, y un reclamo inflado es refutable."),
    "recomendaciones": (
        "Cerrar la brecha de medición admite dos caminos distintos. El primero es nuestro: "
        "verificar las series candidatas ya identificadas, que habilita medir indicadores sin "
        "pedirle nada a nadie. El segundo se dirige al obligado: cuando la ley asigna a un "
        "órgano la producción de un dato y ese dato no consta publicado, la recomendación "
        "nombra el artículo, el deudor y el instrumento con el que se puede exigir.\n\n"
        "Se recomienda la publicación del dato, nunca la política: el informe señala qué falta "
        "y a quién la ley se lo asigna, y no opina sobre qué debería hacerse con el indicador."),
}


def law_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name=DISPLAY, levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("cumplimiento",), narrative_templates=("sector_decision",),
                audience="abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("cumplimiento", "brechas", "recomendaciones"),
                narrative_templates=("sector_decision", "sector_positioning"),
                audience="cliente / comisión", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("cumplimiento", "coherencia_proceso", "brechas", "recomendaciones"),
                narrative_templates=("sector_decision", "sector_positioning"),
                audience="cliente / comisión", cadence="on_demand", price_band="a medida"),
        })


def expediente_fingerprint(expediente_id: str) -> str:
    """Hash de TODOS los archivos del expediente.

    Sin esto, corregir una meta del CSV no movería el payload y la caché —que no tiene TTL—
    seguiría sirviendo el informe viejo para siempre. Ya pasó en esta plataforma con un
    arreglo de contexto que se desplegó y no invalidó nada.
    """
    base = RAIZ / expediente_id.replace("/", "")
    h = hashlib.sha256()
    for ruta in sorted(p for p in base.iterdir() if p.is_file()):
        h.update(ruta.name.encode("utf-8"))
        h.update(ruta.read_bytes())
    return h.hexdigest()[:16]


class LawProduct:
    """``SectorProduct`` de evaluación de leyes. El `scope` es el expediente."""

    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def product_manifest(self) -> SectorProductManifest:
        return law_manifest()

    # ── El sujeto elegible es la LEY, no una entidad ──
    def scope_kind(self) -> str:
        return "entity"

    def scope_options(self) -> List[Dict[str, str]]:
        out = []
        for eid in expedientes():
            e = cargar(eid)
            out.append({"value": eid, "label": f"{e.titulo} ({e.norma})", "group": "Instrumento"})
        return out

    # ── Señales de readiness ──
    def has_engine(self) -> bool:
        return True

    def data_signals(self) -> DataHealth:
        # La frescura de este producto no es la de una serie: es la del EXPEDIENTE, que se
        # actualiza por PR. Se reporta sin inventar una cadencia que no existe.
        # La cobertura reportada acá es la del EXPEDIENTE contra la ley: cuántos de sus
        # indicadores el informe realmente mide. No se inventa una frescura de serie porque
        # el expediente no es una serie — se versiona por PR.
        from modules.law_intel.bindings import cobertura
        eids = expedientes()
        pct = float(cobertura(eids[0])["pct"]) if eids else 0.0   # type: ignore[arg-type]
        return DataHealth(coverage=pct / 100.0, freshness_days=None)

    def validation_state(self) -> ValidationState:
        # El registro está contrastado contra el texto legal (21 metas leídas a mano), pero
        # NINGÚN binding está verificado todavía: el producto no puede afirmar cumplimiento.
        # Declararlo aprobado con cobertura cero sería exactamente lo que el módulo denuncia.
        from modules.law_intel.bindings import cobertura
        eids = expedientes()
        medidos = int(cobertura(eids[0])["medidos"]) if eids else 0  # type: ignore[call-overload]
        return ValidationState(
            approved=bool(medidos), score=1.0 if medidos else 0.0,
            notes=("Registro contrastado contra el articulado. Sin bindings verificados el "
                   "informe no mide cumplimiento: corré /bindings/verificacion."))

    # ── Snapshot ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        disponibles = expedientes()
        if not disponibles:
            raise ValueError("No hay expedientes de ley cargados.")
        eid = scope or disponibles[0]
        if eid not in disponibles:
            raise ValueError(f"No existe el expediente '{eid}'. Disponibles: {disponibles}.")
        corte = (period or "")[:4] or "2025"
        ctx = law_ai_context(eid, corte)
        exp = cargar(eid)
        # `entity_name` solo en los niveles nombrados: el Pulse es agregado y el sensor de
        # anonimización del ensamblador verifica que no se filtre un identificador.
        nombrado = tier != ProductTier.pulse
        return ProductSnapshot(
            tier=tier, period=corte,
            entity_name=f"{exp.titulo} ({exp.norma})" if nombrado else None,
            payload={
                "expediente": eid,
                # La huella entra en el PAYLOAD a propósito: es lo que hace que la caché
                # note un arreglo del registro. Fuera de acá, el fingerprint no la ve.
                "expediente_fingerprint": expediente_fingerprint(eid),
                "instrumento": {"titulo": exp.titulo, "norma": exp.norma},
                "contexto": ctx,
                "sin_dato": secciones_sin_dato(ctx),
            })

    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        secciones = self.product_manifest().require_level(tier).sections
        sin_dato = set((snapshot.payload or {}).get("sin_dato") or [])
        ctx = (snapshot.payload or {}).get("contexto") or {}

        import asyncio

        from shared.narrative.claude_engine import narrative_engine
        from shared.products import section_mode

        out: Dict[str, str] = {}
        pendientes = []
        for sec in secciones:
            # Una sección sin su insumo se DECLARA vacía; no se le pide al modelo que la
            # escriba igual. Un Deep Dive relleno es peor que uno más corto.
            if sec in sin_dato:
                out[sec] = _SIN_DATO
                continue
            propio = dict(ctx)
            propio["seccion_pedida"] = _SECTION_TITLES.get(sec, sec)
            pendientes.append((sec, dict(
                context=propio, template="sector_decision",
                mode=section_mode(tier, sec, secciones),
                axis="law_intel", audience="cliente / comisión")))

        async def _gen(sec: str, kw: Dict[str, Any]):
            res = await narrative_engine.generate(**kw)
            return sec, res.text

        for sec, texto in await asyncio.gather(*(_gen(s_, k) for s_, k in pendientes)):
            out[sec] = texto
        return out

    # ── Muestra de conversión ──
    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        """Narrativa CURADA de la muestra. NO usa el motor de IA.

        Enseña la anatomía del informe sobre un instrumento ficticio: cobertura declarada,
        veredictos sin eufemismo, brecha con responsable y recomendación con base legal. Nada
        de lo que dice se refiere a una ley real.
        """
        return {sec: _SAMPLE_NARRATIVES[sec]
                for sec in self.product_manifest().require_level(tier).sections}


    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        """Demo con un instrumento FICTICIO, no con una ley real.

        Deliberado: una muestra con marca de agua de la evaluación de una ley real puede
        circular como si fuera el dictamen, y en este dominio eso es un daño concreto para el
        instrumento evaluado. La muestra enseña la ANATOMÍA del informe —cobertura declarada,
        brecha con responsable, recomendación con base legal— sin afirmar nada de nadie.
        """
        ctx = {
            "instrumento": {"titulo": "Ley de ejemplo", "norma": "Ley 000-00",
                            "vigencia_hasta": "2035-12-31", "corte_evaluado": "2025"},
            "cobertura_indicadores_medidos_sobre_total_de_la_ley": {
                "medidos": 12, "total_indicadores_numerados": 30, "pct": 40.0,
                "propuestos_sin_verificar": 4,
                "advertencia": "Un binding propuesto NO es una medición."},
            "denominadores_del_registro": {"indicadores_numerados_de_la_ley": 30,
                                           "filas_medibles_con_subfilas": 41, "nota": "demo"},
            "veredictos_por_indicador_computados": {
                "total": 30, "evaluados": 12, "cumplen": 5, "pct_sobre_evaluados": 41.7,
                "por_veredicto": {"alcanzada": 5, "no_alcanzara": 6, "retrocede": 1,
                                  "sin_medicion": 18},
                "nota": "El porcentaje se computa sobre los EVALUADOS."},
            "contradicciones_proceso_vs_resultado_computadas": [],
            "obligaciones_del_instrumento": {"total": 3, "por_estado": {"incumplida": 1,
                                                                        "cumplida": 2}},
            "frases_publicables_de_obligaciones": [],
            "regla_de_afirmacion": "demo",
            "brechas_de_medicion": {"total_indicadores_ley": 30, "con_brecha": 18,
                                    "por_responsable": {"sdq": 14, "instrumento": 4}},
            "recomendaciones_ya_redactadas": [
                {"clase": "publicacion", "texto": "Ejemplo de recomendación con base legal.",
                 "desbloquea_indicadores": 0}],
            "alcance_de_la_recomendacion": ("Se recomienda la PUBLICACIÓN del dato, nunca la "
                                            "política."),
        }
        nombrado = tier != ProductTier.pulse
        return ProductSnapshot(
            tier=tier, period="2025",
            entity_name="Ley de ejemplo (Ley 000-00)" if nombrado else None,
            payload={"expediente": "demo", "expediente_fingerprint": "demo",
                     "instrumento": ctx["instrumento"], "contexto": ctx, "sin_dato": []})

    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None,
                     fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        ctx = (snapshot.payload or {}).get("contexto") or {}
        inst = (snapshot.payload or {}).get("instrumento") or {}
        cob = ctx.get("cobertura_indicadores_medidos_sobre_total_de_la_ley") or {}

        tables: List[Any] = []
        # La portada dice la cobertura CON su denominador. Una cifra de panel escrita en
        # prosa se vuelve mentira en la próxima corrida; la tabla se regenera.
        tables.append(("Cobertura de la evaluación", [
            ["Concepto", "Valor"],
            ["Indicadores que la ley fija", str(cob.get("total_indicadores_numerados", "—"))],
            ["Medidos por este informe", str(cob.get("medidos", "—"))],
            ["Con serie propuesta sin verificar", str(cob.get("propuestos_sin_verificar", "—"))],
        ]))
        recs = ctx.get("recomendaciones_ya_redactadas") or []
        if recs:
            tables.append(("Qué se puede exigir", [["Clase", "Recomendación", "Desbloquea"]] + [
                [r["clase"], r["texto"][:180], str(r["desbloquea_indicadores"])]
                for r in recs[:12]]))

        medidos, total = cob.get("medidos"), cob.get("total_indicadores_numerados")
        headline = (f"Mide {medidos} de {total} indicadores"
                    if medidos is not None and total else None)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=DISPLAY,
            title=f"{inst.get('titulo') or 'Instrumento'} · {inst.get('norma') or ''}".strip(" ·"),
            period=snapshot.period, narratives=narratives, section_titles=_SECTION_TITLES,
            tables=tables, charts=[], headline=headline, subtitle=None,
            watermark=level.watermark, sample=sample, output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: LawProduct(db))
