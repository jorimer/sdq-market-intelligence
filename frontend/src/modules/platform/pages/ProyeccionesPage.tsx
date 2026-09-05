import { useEffect, useState } from "react";
import { LineChart, CheckCircle2, CircleDashed, ShieldQuestion } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock } from "@/shared/ui/primitives";
import { Markdown } from "@/shared/ui/Markdown";
import { mensajeDeError } from "@/shared/api/errores";
import { getProductReport, esAbortada, type ProductReport } from "../api";

/* ──────────────────────────────────────────────────────────────────
 * Proyecciones Macro — la herramienta prospectiva.
 *
 * CONVIVE con su entrada del catálogo, no la reemplaza: es el mismo producto
 * (`insight:macro_forecast`) con dos puertas, igual que Research a Medida, que
 * tiene su SKU y su página. Por eso esta pantalla NO implementa control de
 * acceso propio — pide el reporte por el endpoint del producto, donde el gate
 * de activación y tier ya corre en la dependency. Reimplementarlo acá sería
 * abrir una segunda definición de quién puede ver qué, y las dos se
 * contradicen el día que una cambia.
 *
 * Lo que esta página agrega sobre el catálogo genérico es la LECTURA: el
 * catálogo sirve la prosa; acá el payload estructurado se muestra como lo que
 * es —proyecciones con su banda, la cifra determinada, la desagregación
 * sectorial y el track record—, que es como se juzga un pronóstico.
 * ────────────────────────────────────────────────────────────────── */

const SECTOR = "macro_forecast";

interface Proyeccion {
  serie: string;
  horizonte: string;
  punto: number;
  intervalos: number[][];
  modelo: string;
  as_of: string;
  ancla: boolean;
  motivo: string;
  n_oos: number;
}
interface CifraDeterminada {
  trimestre: string;
  indice: number;
  dlog_pct: number | null;
  diferencia_maxima_historica: number;
}
interface SectorFila {
  etiqueta: string;
  crecimiento: number;
  peso: number;
  incidencia: number;
}
interface Desempeno {
  modelo: string;
  serie: string;
  horizonte: string;
  n_oos: number;
  rmse: number | null;
  mae: number | null;
  interval_coverage: number[][];
  solapan: boolean | null;
}

const pct = (v: number, d = 2) => `${v.toFixed(d)} %`;

/** La banda de un nivel, o "—". El nivel se busca; no se asume que sea el primero. */
function banda(intervalos: number[][] | undefined, nivel: number): string {
  const t = (intervalos ?? []).find((x) => x.length >= 3 && Math.abs(x[0] - nivel) < 1e-9);
  return t ? `${t[1].toFixed(2)} … ${t[2].toFixed(2)}` : "—";
}

/* ── El sello que importa: ¿esta cifra puede sostener una afirmación? ── */
function SelloDeAnclaje({ ancla, motivo }: { ancla: boolean; motivo: string }) {
  if (ancla) {
    return (
      <Chip tone="ok">
        <CheckCircle2 className="w-3.5 h-3.5" /> Ancla una afirmación
      </Chip>
    );
  }
  return (
    <span className="inline-flex flex-col gap-1">
      <Chip tone="warn">
        <CircleDashed className="w-3.5 h-3.5" /> No ancla todavía
      </Chip>
      {motivo && <span className="text-xs text-muted max-w-xs">{motivo}</span>}
    </span>
  );
}

export function ProyeccionesPage() {
  const [report, setReport] = useState<ProductReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        setCargando(true);
        // Se pide el nivel de suscripción; el backend degrada al que corresponda al
        // tier del usuario y devuelve cuál sirvió en `tier`.
        const r = await getProductReport(SECTOR, "insight", {}, ctrl.signal);
        setReport(r);
        setError(null);
      } catch (e: unknown) {
        if (esAbortada(e)) return;
        // Por el helper compartido y no leyendo `detail` a mano: FastAPI lo devuelve como
        // texto, objeto (402 de upsell, 429 de cuota) o lista (422). Acá el 402 es el caso
        // NORMAL —quien no tiene la suscripción llega por esta puerta— y leerlo crudo
        // pondría «[object Object]» justo en la pantalla que tiene que invitar a comprar.
        setError(mensajeDeError(e, "No se pudo cargar la proyección."));
      } finally {
        setCargando(false);
      }
    })();
    return () => ctrl.abort();
  }, []);

  const p = (report?.payload ?? {}) as {
    proyecciones?: Proyeccion[];
    cifra_determinada?: CifraDeterminada | null;
    sectorial?: { horizonte: string; ajuste_pp: number; sectores: SectorFila[];
                  brechas?: Record<string, string> } | null;
    desempeno?: Desempeno[];
    escenarios?: { horizonte: string; punto: number; intervalos: number[][] }[];
  };

  return (
    <>
      <PageHead
        eyebrow="Herramientas"
        title="Proyecciones Macro"
        sub="Nowcast del trimestre en curso, trayectoria del PIB y desagregación sectorial — cada cifra con su banda y con el historial de acierto del modelo que la produjo."
        right={
          report ? (
            <Chip tone="muted">
              <LineChart className="w-3.5 h-3.5" /> corte {report.period ?? "—"}
            </Chip>
          ) : undefined
        }
      />

      {cargando && <StateBlock kind="loading" />}

      {!cargando && error && (
        <StateBlock kind="error" title="Proyecciones no disponibles" message={error} />
      )}

      {!cargando && !error && report && (
        <div className="space-y-4">
          {/* ── La cifra determinada. No es un pronóstico y la página lo dice. ── */}
          {p.cifra_determinada && (
            <Card>
              <CardHead
                title={`PIB ${p.cifra_determinada.trimestre} · determinado`}
                right={<Chip tone="ok">Aritmética, no pronóstico</Chip>}
              />
              <div className="px-4 pb-4">
                <div className="font-display text-[30px] font-extrabold text-ink">
                  {p.cifra_determinada.indice.toFixed(6)}
                  {p.cifra_determinada.dlog_pct != null && (
                    <span className="text-[15px] font-bold text-body ml-3">
                      {p.cifra_determinada.dlog_pct >= 0 ? "+" : ""}
                      {p.cifra_determinada.dlog_pct.toFixed(4)} % vs. trimestre anterior
                    </span>
                  )}
                </div>
                <p className="text-sm text-muted mt-2 max-w-3xl">
                  Con los tres meses del IMAE publicados, el promedio trimestral del índice{" "}
                  <strong>es</strong> el índice de volumen del PIB — una identidad de
                  construcción del BCRD, verificada en cada lectura (diferencia máxima
                  histórica {p.cifra_determinada.diferencia_maxima_historica.toFixed(4)}{" "}
                  puntos). Por eso se sirve <strong>sin banda de error</strong>: ponerle una
                  la disfrazaría de pronóstico. Queda determinada unos quince días antes de
                  que el BCRD publique el PIB.
                </p>
              </div>
            </Card>
          )}

          {/* ── Trayectoria ── */}
          <Card>
            <CardHead title="Trayectoria proyectada" />
            <div className="px-4 pb-4 overflow-x-auto">
              {(p.proyecciones ?? []).length === 0 ? (
                <p className="text-sm text-muted">
                  No hay proyecciones vigentes para este corte.
                </p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-xs text-muted">
                    <tr className="text-left">
                      <th className="py-2 pr-4">Serie</th>
                      <th className="py-2 pr-4">Horizonte</th>
                      <th className="py-2 pr-4 text-right">Punto</th>
                      <th className="py-2 pr-4">Banda 80 %</th>
                      <th className="py-2 pr-4">Modelo</th>
                      <th className="py-2">Respaldo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(p.proyecciones ?? []).map((d) => (
                      <tr key={`${d.serie}-${d.horizonte}`} className="border-t border-hair">
                        <td className="py-2.5 pr-4 text-ink">{d.serie}</td>
                        <td className="py-2.5 pr-4">{d.horizonte}</td>
                        <td className="py-2.5 pr-4 text-right font-semibold text-ink">
                          {pct(d.punto)}
                        </td>
                        <td className="py-2.5 pr-4 text-body">{banda(d.intervalos, 0.8)}</td>
                        <td className="py-2.5 pr-4 text-xs text-muted">{d.modelo}</td>
                        <td className="py-2.5">
                          <SelloDeAnclaje ancla={d.ancla} motivo={d.motivo} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </Card>

          {/* ── Escenarios: existen y NO son pronósticos ── */}
          {(p.escenarios ?? []).length > 0 && (
            <Card>
              <CardHead
                title="Escenarios a 3-8 trimestres"
                right={
                  <Chip tone="warn">
                    <ShieldQuestion className="w-3.5 h-3.5" /> Sin track record
                  </Chip>
                }
              />
              <div className="px-4 pb-4">
                <p className="text-sm text-muted mb-3 max-w-3xl">
                  No son pronósticos. Más allá de dos trimestres, la ventaja del modelo sobre
                  un random walk <strong>no sobrevive</strong> a excluir la pandemia de la
                  muestra, así que no se le publica historial de acierto. Ninguno de estos
                  números puede sostener una afirmación anclada.
                </p>
                <div className="flex flex-wrap gap-2">
                  {(p.escenarios ?? []).map((e) => (
                    <Chip key={e.horizonte} tone="muted">
                      {e.horizonte}: {pct(e.punto)} · {banda(e.intervalos, 0.8)}
                    </Chip>
                  ))}
                </div>
              </div>
            </Card>
          )}

          {/* ── Sectorial ── */}
          {p.sectorial && p.sectorial.sectores.length > 0 && (
            <Card>
              <CardHead
                title={`Lectura sectorial · ${p.sectorial.horizonte}`}
                right={<Chip tone="ok">Reconcilia exacto con el agregado</Chip>}
              />
              <div className="px-4 pb-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs text-muted">
                    <tr className="text-left">
                      <th className="py-2 pr-4">Actividad</th>
                      <th className="py-2 pr-4 text-right">Peso</th>
                      <th className="py-2 pr-4 text-right">Crecimiento</th>
                      <th className="py-2 text-right">Incidencia</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.sectorial.sectores.map((s) => (
                      <tr key={s.etiqueta} className="border-t border-hair">
                        <td className="py-2.5 pr-4 text-ink">{s.etiqueta}</td>
                        <td className="py-2.5 pr-4 text-right text-body">
                          {(s.peso * 100).toFixed(2)} %
                        </td>
                        <td className="py-2.5 pr-4 text-right text-body">
                          {pct(s.crecimiento)}
                        </td>
                        <td className="py-2.5 text-right font-semibold text-ink">
                          {s.incidencia.toFixed(3)} pp
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-xs text-muted mt-3 max-w-3xl">
                  Ajuste de reconciliación: {p.sectorial.ajuste_pp >= 0 ? "+" : ""}
                  {p.sectorial.ajuste_pp.toFixed(3)} pp por actividad, repartido proporcional
                  al <strong>peso</strong> y no al crecimiento — repartir por crecimiento le
                  pega más al que más se mueve y puede darle vuelta el signo a un sector, que
                  es justo la lectura que esta sección existe para dar.
                </p>
                {p.sectorial.brechas && Object.keys(p.sectorial.brechas).length > 0 && (
                  <p className="text-xs text-warn mt-2">
                    No proyectadas: {Object.keys(p.sectorial.brechas).join(", ")}. Una
                    actividad con huecos se declara, no se rellena.
                  </p>
                )}
              </div>
            </Card>
          )}

          {/* ── El track record, EN EL CUERPO ── */}
          <Card>
            <CardHead title="Desempeño de nuestras proyecciones anteriores" />
            <div className="px-4 pb-4 overflow-x-auto">
              {(p.desempeno ?? []).length === 0 ? (
                <p className="text-sm text-muted max-w-3xl">
                  Todavía no hay pronósticos puntuados: ninguna de las proyecciones emitidas
                  alcanzó su período de cierre con el dato observado publicado. Esta sección
                  se llena sola a medida que los trimestres cierran, y aparece con o sin
                  resultados — un desempeño que solo se publica cuando conviene no es un
                  track record.
                </p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-xs text-muted">
                    <tr className="text-left">
                      <th className="py-2 pr-4">Modelo</th>
                      <th className="py-2 pr-4">Horizonte</th>
                      <th className="py-2 pr-4 text-right">n</th>
                      <th className="py-2 pr-4 text-right">RMSE</th>
                      <th className="py-2">Calibración del intervalo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(p.desempeno ?? []).map((f) => (
                      <tr key={`${f.modelo}-${f.horizonte}`} className="border-t border-hair">
                        <td className="py-2.5 pr-4 text-xs text-ink">{f.modelo}</td>
                        <td className="py-2.5 pr-4">{f.horizonte}</td>
                        <td className="py-2.5 pr-4 text-right">{f.n_oos}</td>
                        <td className="py-2.5 pr-4 text-right">
                          {f.rmse != null ? f.rmse.toFixed(3) : "—"}
                        </td>
                        <td className="py-2.5 text-xs text-body">
                          {(f.interval_coverage ?? []).length === 0
                            ? "sin puntuar"
                            : (f.interval_coverage ?? [])
                                .map(
                                  ([n, c, k]) =>
                                    `el del ${(n * 100).toFixed(0)} % acertó el ${(c * 100).toFixed(0)} % (n=${k})`,
                                )
                                .join("; ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </Card>

          {/* ── La prosa que el motor computa, tal cual ── */}
          {report.commercial.sections
            .filter((s) => report.narratives[s])
            .map((s) => (
              <Card key={s}>
                <CardHead title={s === "methodology" ? "Metodología y límites" : s} />
                <div className="px-4 pb-4">
                  <Markdown text={report.narratives[s]} />
                </div>
              </Card>
            ))}
        </div>
      )}
    </>
  );
}
