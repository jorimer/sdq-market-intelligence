import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Wrench } from "lucide-react";
import { Card, CardHead, StateBlock } from "@/shared/ui/primitives";
import { UsoDeHerramientas, getUsoDeHerramientas } from "@/shared/ops/api";

/**
 * Corridas de las tres herramientas comerciales, dentro de la consola de Operaciones.
 *
 * Es la única capa del sistema con costo variable real por ejecución, y hasta ahora no
 * tenía contador: "cuántas veces se usó Deal Scoring este mes" no tenía respuesta, y sin
 * ella cualquier decisión sobre su empaque comercial es una impresión.
 *
 * MIDE; no restringe. No hay cuota ni gate: poner un techo es una decisión que se toma con
 * estos números, no antes de tenerlos.
 *
 * Data-driven a propósito: la lista de herramientas y de acciones sale del backend. Una
 * herramienta nueva aparece sola — no hay una segunda lista acá que se pueda olvidar de
 * actualizar, que es como un tipo nuevo desaparece de una superficie sin que nada falle.
 */
export function HerramientasPanel() {
  const { t } = useTranslation();
  const [data, setData] = useState<UsoDeHerramientas | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready" | "forbidden">("loading");

  const load = useCallback(async () => {
    try {
      setData(await getUsoDeHerramientas());
      setStatus("ready");
    } catch (e: unknown) {
      const code = (e as { response?: { status?: number } })?.response?.status;
      setStatus(code === 403 ? "forbidden" : "error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (status === "forbidden") return null;

  const filas = data?.por_herramienta ?? [];

  return (
    <Card>
      <CardHead
        icon={Wrench}
        title={t("ops.herramientas.title")}
        subtitle={t("ops.herramientas.sub")}
      />
      {status === "loading" && <StateBlock kind="loading" message={t("ops.loading")} />}
      {status === "error" && <StateBlock kind="error" message={t("ops.loadError")} />}
      {status === "ready" && filas.length === 0 && (
        <StateBlock kind="empty" message={t("ops.herramientas.empty")} />
      )}
      {status === "ready" && filas.length > 0 && data && (
        <>
          <div className="mb-3 text-sm text-slate-600">
            {t("ops.herramientas.rango", {
              desde: data.desde,
              hasta: data.hasta,
              total: data.corridas_totales_de_las_herramientas,
            })}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-3">{t("ops.herramientas.colHerramienta")}</th>
                  <th className="py-2 pr-3 text-right">{t("ops.herramientas.colCorridas")}</th>
                  <th className="py-2 pr-3 text-right">{t("ops.herramientas.colFallidas")}</th>
                  <th className="py-2 pr-3 text-right">{t("ops.herramientas.colUsuarios")}</th>
                  <th className="py-2">{t("ops.herramientas.colAcciones")}</th>
                </tr>
              </thead>
              <tbody>
                {filas.map((h) => (
                  <tr key={h.herramienta} className="border-b border-slate-100 align-top">
                    <td className="py-2 pr-3 font-medium text-slate-800">{h.etiqueta}</td>
                    <td className="py-2 pr-3 text-right tabular-nums text-slate-800">
                      {h.corridas_de_la_herramienta}
                    </td>
                    {/* Las fallidas se muestran aparte y no se restan del total: una corrida
                        que falla cuesta igual, y esconderla haría ver más barata la
                        herramienta que peor funciona. */}
                    <td className="py-2 pr-3 text-right tabular-nums text-slate-500">
                      {h.corridas_fallidas_de_la_herramienta}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-slate-500">
                      {h.usuarios_distintos_de_la_herramienta}
                    </td>
                    <td className="py-2 text-slate-600 text-xs">
                      {/* El desglose por acción, porque "marca: 40 corridas" mezcla leer un
                          mazo de 60 láminas con abrir un informe ya calculado. */}
                      {(data.por_accion ?? [])
                        .filter((a) => a.herramienta === h.herramienta)
                        .map((a) => `${a.accion}: ${a.corridas_de_la_accion}`)
                        .join(" · ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}
