import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldCheck } from "lucide-react";
import { Card, CardHead, StateBlock } from "@/shared/ui/primitives";
import { FrescuraEje, FrescuraValidacion, getValidacionFrescura } from "@/shared/ops/api";

/**
 * Frescura de la validación por eje, dentro de la consola de Operaciones.
 *
 * La consola ya decía CUÁNDO corrió cada operación. Esa es otra pregunta, y es la que no
 * alcanzó: el backtest de banca había corrido "hace tres semanas" sin nada anómalo a la
 * vista, mientras el score que medía ya no era el mismo. Producción sirvió un Gini de 0,44
 * durante 19 días contra un deck que decía 0,16.
 *
 * Tres estados, y el tercero no es un detalle: `vigente`, `obsoleto` e `indeterminado`. Un
 * reporte del que no se puede saber si está al día NO se pinta en verde — confundir "no sé"
 * con "está bien" es exactamente cómo se publicó el número viejo.
 */

type Estado = "vigente" | "obsoleto" | "indeterminado";

function estadoDe(e: FrescuraEje): Estado {
  if (e.stale === false) return "vigente";
  if (e.stale === true) return "obsoleto";
  return "indeterminado";
}

const TONO: Record<Estado, string> = {
  vigente: "bg-emerald-50 text-emerald-700 border-emerald-200",
  obsoleto: "bg-red-50 text-red-700 border-red-200",
  indeterminado: "bg-amber-50 text-amber-700 border-amber-200",
};

function fecha(iso: string | null | undefined, locale: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString(locale);
}

export function FrescuraPanel() {
  const { t, i18n } = useTranslation();
  const locale = i18n.language === "en" ? "en-US" : i18n.language === "fr" ? "fr-FR" : "es-DO";
  const [data, setData] = useState<FrescuraValidacion | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready" | "forbidden">("loading");

  const load = useCallback(async () => {
    try {
      setData(await getValidacionFrescura());
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

  const ejes = data?.ejes ?? [];

  return (
    <Card>
      <CardHead icon={ShieldCheck} title={t("ops.frescura.title")} subtitle={t("ops.frescura.sub")} />
      {status === "loading" && <StateBlock kind="loading" message={t("ops.loading")} />}
      {status === "error" && <StateBlock kind="error" message={t("ops.loadError")} />}
      {status === "ready" && ejes.length === 0 && (
        <StateBlock kind="empty" message={t("ops.frescura.empty")} />
      )}
      {status === "ready" && ejes.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-200">
                <th className="py-2 pr-3">{t("ops.frescura.colEje")}</th>
                <th className="py-2 pr-3">{t("ops.frescura.colEstado")}</th>
                <th className="py-2 pr-3">{t("ops.frescura.colFecha")}</th>
                <th className="py-2">{t("ops.frescura.colMotivo")}</th>
              </tr>
            </thead>
            <tbody>
              {ejes.map((e) => {
                const estado = estadoDe(e);
                return (
                  <tr key={e.eje} className="border-b border-slate-100 align-top">
                    <td className="py-2 pr-3 font-medium text-slate-800">
                      {e.eje}
                      <div className="text-xs text-slate-400">{e.operacion}</div>
                    </td>
                    <td className="py-2 pr-3">
                      <span className={`inline-block rounded border px-2 py-0.5 text-xs ${TONO[estado]}`}>
                        {t(`ops.frescura.${estado}`)}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-slate-600">{fecha(e.generated_at, locale)}</td>
                    <td className="py-2 text-slate-600">
                      {!e.tiene_reporte
                        ? t("ops.frescura.sinReporte")
                        : e.stale_reason ?? "—"}
                      {/* Lo que la huella NO cubre viaja con el verde: un "vigente" que
                          calla su alcance afirma más de lo que se verificó. */}
                      {e.stale_scope && e.stale_scope.length > 0 && (
                        <div className="text-xs text-amber-700 mt-1">
                          {t("ops.frescura.noCubre")}: {e.stale_scope.join(" · ")}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
