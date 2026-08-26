/**
 * «Qué movió el score» — la atribución del cambio, por ventana, en la vista in-app.
 *
 * **Por qué existe este componente.** La tabla se computaba desde hacía tiempo y se dibujaba
 * en el PDF; la vista in-app del mismo Deep Dive no la mostraba. Un producto que dice cosas
 * distintas según se mire en pantalla o se descargue es la doctrina del repo al revés:
 * «aplica al contexto de IA y a la tabla renderizada: son superficies distintas y arreglar
 * una sola deja el documento contradiciéndose».
 *
 * **Lo que aporta sobre el gráfico de dimensiones que ya estaba.** Las barras muestran el
 * NIVEL de cada dimensión; esto muestra el MOVIMIENTO y de quién fue. No son lo mismo y la
 * confusión tiene precio: la dimensión que más se movió NO es la que más movió el resultado,
 * porque los pesos difieren. Un informe entregado atribuyó el deterioro de un semestre al
 * «colapso de eficiencia» cuando en ese semestre la eficiencia MEJORÓ y aportó a favor.
 *
 * **La fila de total no es decoración.** Los aportes de cada ventana SUMAN el cambio total,
 * y mostrarlo es lo que vuelve la atribución auditable contra la mesa: si no cuadra, se ve.
 */
import { useTranslation } from "react-i18next";

import type { VentanaDeCambio } from "../api";
import { componentesDeAportes } from "../api";

/** `+1.90` / `−0.34` / `—`. El signo explícito: un aporte sin signo no dice nada. */
function pts(v: number | null | undefined): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;
}

function tono(v: number | null | undefined): string {
  if (typeof v !== "number" || Number.isNaN(v) || v === 0) return "text-muted";
  return v > 0 ? "text-ok" : "text-alert";
}

export function AportesAlCambio({ ventanas }: { ventanas: VentanaDeCambio[] }) {
  const { t } = useTranslation();
  if (!ventanas.length) return null;
  const componentes = componentesDeAportes(ventanas);
  if (!componentes.length) return null;

  return (
    <div className="space-y-2">
      <div className="text-[11px] uppercase tracking-wide text-faint">
        {t("platform.catalog.aportes.title", "Qué movió el score")}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[420px]">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-faint">
              <th className="py-1.5 pr-3 font-normal">
                {t("platform.catalog.aportes.componente", "Dimensión")}
              </th>
              {ventanas.map((v) => (
                <th key={v.ventana} className="py-1.5 px-2 font-normal text-right">
                  {v.ventana}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {componentes.map((c) => (
              <tr key={c} className="border-t border-line">
                <td className="py-1.5 pr-3 capitalize">{c}</td>
                {ventanas.map((v) => {
                  const a = v.aportes.find((x) => x.componente === c);
                  return (
                    <td
                      key={v.ventana}
                      className={`py-1.5 px-2 text-right tabular-nums ${tono(a?.aporte_al_cambio)}`}
                    >
                      {pts(a?.aporte_al_cambio)}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="border-t border-line font-medium">
              <td className="py-1.5 pr-3">
                {t("platform.catalog.aportes.total", "Cambio total")}
              </td>
              {ventanas.map((v) => (
                <td
                  key={v.ventana}
                  className={`py-1.5 px-2 text-right tabular-nums ${tono(v.cambio_total)}`}
                >
                  {pts(v.cambio_total)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="text-[11px] leading-snug text-muted">
        {t(
          "platform.catalog.aportes.caveat",
          "Aporte = cambio de la dimensión × su peso en la rúbrica del tipo de entidad. " +
            "Cada columna suma el cambio total, así que la dimensión que más se movió no es " +
            "necesariamente la que más movió el resultado.",
        )}
      </p>
    </div>
  );
}
