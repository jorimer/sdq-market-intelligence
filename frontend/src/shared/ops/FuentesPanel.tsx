import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Radio } from "lucide-react";
import { Card, CardHead, StateBlock } from "@/shared/ui/primitives";
import { FuenteDeEje, FuentesDeLosEjes, getFuentesDeLosEjes } from "@/shared/ops/api";

/**
 * Fuentes de los ejes, dentro de la consola de Operaciones.
 *
 * La consola de abajo dice si cada operación corrió a tiempo. Esa es otra pregunta, y es
 * la que no alcanza: un sync puede correr en verde para siempre contra un archivo que la
 * fuente dejó de actualizar. La sección de estadísticas de la SIE lleva años así —su
 * propio slug en el portal declara la serie terminada— y el eje aparenta estar vivo.
 *
 * Tres estados, y el tercero no es un detalle: `al día`, `congelada` e `indeterminada`.
 * Un eje cuya antigüedad no se puede medir NO se pinta en verde — confundir "no sé de
 * cuándo es" con "está al día" es como se publica un número viejo sin que nadie se entere.
 * Y lo indeterminado se lista: un veto silencioso se lee como que el eje no tiene problema.
 */

const TONO: Record<string, string> = {
  al_dia: "bg-emerald-50 text-emerald-700 border-emerald-200",
  congelada: "bg-red-50 text-red-700 border-red-200",
  indeterminada: "bg-amber-50 text-amber-700 border-amber-200",
};

/** El orden de lectura: primero lo que hay que atender. */
const ORDEN: Record<string, number> = { congelada: 0, indeterminada: 1, al_dia: 2 };

/** Un estado que el backend agregue y la UI no conozca cae a "indeterminado", nunca a
 *  "al día": una etiqueta desconocida no puede leerse como que el eje está bien. */
/** El `detail` que declara cada producto es libre y algunos son largos —el de valuación son
 *  ocho renglones— y sin tope una sola fila desbaloncea la tabla entera. Se recorta para
 *  leer y el texto íntegro queda en el título emergente: acortar en pantalla es distinto de
 *  perder el dato. */
const DETALLE_MAX = 150;

function recortar(texto: string): string {
  return texto.length > DETALLE_MAX ? `${texto.slice(0, DETALLE_MAX).trimEnd()}…` : texto;
}

const ETIQUETA: Record<string, string> = {
  al_dia: "ops.fuentes.al_dia",
  congelada: "ops.fuentes.congelada",
  indeterminada: "ops.fuentes.indeterminada",
};

export function FuentesPanel() {
  const { t } = useTranslation();
  const [data, setData] = useState<FuentesDeLosEjes | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready" | "forbidden">("loading");

  const load = useCallback(async () => {
    try {
      setData(await getFuentesDeLosEjes());
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

  const ejes: FuenteDeEje[] = [...(data?.ejes ?? [])].sort(
    (a, b) => (ORDEN[a.estado] ?? 9) - (ORDEN[b.estado] ?? 9) || a.id.localeCompare(b.id),
  );
  const nCongeladas = data?.congeladas.length ?? 0;
  const nIndeterminadas = data?.indeterminadas.length ?? 0;

  return (
    <Card>
      <CardHead icon={Radio} title={t("ops.fuentes.title")} subtitle={t("ops.fuentes.sub")} />
      {status === "loading" && <StateBlock kind="loading" message={t("ops.loading")} />}
      {status === "error" && <StateBlock kind="error" message={t("ops.loadError")} />}
      {status === "ready" && ejes.length === 0 && (
        <StateBlock kind="empty" message={t("ops.fuentes.empty")} />
      )}
      {status === "ready" && ejes.length > 0 && (
        <>
          {/* El recuento de indeterminados va ARRIBA y no escondido al pie: son los ejes
              sobre los que el sensor no afirma nada, y no saberlo se lee como que están bien. */}
          <div className="mb-3 text-sm text-slate-600">
            {t("ops.fuentes.resumen", { congeladas: nCongeladas, indeterminadas: nIndeterminadas })}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-3">{t("ops.fuentes.colEje")}</th>
                  <th className="py-2 pr-3">{t("ops.fuentes.colEstado")}</th>
                  <th className="py-2 pr-3">{t("ops.fuentes.colEdad")}</th>
                  <th className="py-2">{t("ops.fuentes.colMotivo")}</th>
                </tr>
              </thead>
              <tbody>
                {ejes.map((e) => (
                  <tr key={e.id} className="border-b border-slate-100 align-top">
                    <td className="py-2 pr-3 font-medium text-slate-800">
                      {e.eje}
                      {/* Qué fuente del eje es esta fila. Sin el rótulo, dos filas del mismo
                          eje con veredictos opuestos se leen como una contradicción. */}
                      {e.clave && (
                        <span className="ml-2 text-xs font-normal text-slate-500">
                          · {t("ops.fuentes.feed")}
                        </span>
                      )}
                      {/* El emisor viaja con el eje: sin él la fila no es accionable. */}
                      <div className="text-xs text-slate-400">
                        {e.fuentes.length > 0 ? e.fuentes.join(" · ") : t("ops.fuentes.sinEmisor")}
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <span
                        className={`inline-block rounded border px-2 py-0.5 text-xs ${
                          TONO[e.estado] ?? TONO.indeterminada
                        }`}
                      >
                        {t(ETIQUETA[e.estado] ?? ETIQUETA.indeterminada)}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-slate-600 whitespace-nowrap">
                      {/* La edad NUNCA se muestra sola: al lado va el tope contra el que se
                          juzga, o "600 días" no dice si es mucho. */}
                      {e.dias_desde_el_periodo_del_dato === null
                        ? "—"
                        : t("ops.fuentes.edad", {
                            dias: e.dias_desde_el_periodo_del_dato,
                            tope: e.tope_de_dias_de_la_cadencia ?? "—",
                          })}
                    </td>
                    <td className="py-2 text-slate-600">
                      {e.motivo}
                      {e.detalle_del_producto && (
                        <div
                          className="text-xs text-slate-400 mt-1"
                          title={e.detalle_del_producto}
                        >
                          {recortar(e.detalle_del_producto)}
                        </div>
                      )}
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
