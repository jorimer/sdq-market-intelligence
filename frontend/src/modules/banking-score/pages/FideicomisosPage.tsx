import { useEffect, useState } from "react";
import { Landmark, Info } from "lucide-react";
import { PageHead, Card, CardHead, StateBlock, LoadingGrid } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { getTrusts, TrustRow } from "../api";

const BAND_CLASS: Record<string, string> = {
  "Sólida": "text-ok bg-ok-soft",
  "Estable": "text-accent-ink bg-accent-soft",
  "En vigilancia": "text-warn bg-warn-soft",
  "Frágil": "text-alert bg-alert-soft",
  "N/D": "text-muted bg-surface2",
};

const SEGMENT_LABEL: Record<string, string> = {
  operativo: "Operativo",
  tenedor: "Tenedor",
  desarrollo: "Desarrollo",
  indeterminado: "—",
};

function HealthBadge({ band }: { band: string }) {
  return (
    <span className={`inline-flex items-center rounded-[8px] px-2 py-0.5 text-xs font-semibold ${BAND_CLASS[band] ?? BAND_CLASS["N/D"]}`}>
      {band}
    </span>
  );
}

/** Millions of RD$ (the trust statements are in pesos). */
function mm(v: number | null | undefined): string {
  if (v === null || v === undefined) return "N/D";
  return fmtNum(v / 1_000_000, 0);
}

function dimCell(value: number | null) {
  return (
    <span className="mono text-sm text-ink tabular-nums">
      {value === null ? <span className="text-faint">N/D</span> : fmtNum(value, 0)}
    </span>
  );
}

export function FideicomisosPage() {
  const [rows, setRows] = useState<TrustRow[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    getTrusts()
      .then((r) => active && setRows(r))
      .catch(() => active && setError(true));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div>
      <PageHead
        eyebrow="SIB · Fideicomisos públicos"
        title="Fideicomisos públicos"
        sub="Índice de Salud del Fideicomiso — escala propia (no la escala SDQ de entidades), sobre estados auditados."
      />

      <Card className="mb-5">
        <div className="flex items-start gap-2 text-sm text-muted">
          <Info className="w-4 h-4 mt-0.5 shrink-0 text-faint" />
          <p className="leading-relaxed">
            Los fideicomisos son patrimonios autónomos muy heterogéneos (una concesión
            operativa apalancada vs. un fondo tenedor de activos), por lo que <span className="text-body font-medium">no</span> se
            califican en la escala SDQ-AAA…D. El índice combina <span className="text-body font-medium">solvencia patrimonial</span>,{" "}
            <span className="text-body font-medium">liquidez</span> y <span className="text-body font-medium">sostenibilidad</span>; el
            apalancamiento se muestra como contexto (segmento), no puntúa. Cifras en RD$ millones.
          </p>
        </div>
      </Card>

      {error ? (
        <StateBlock kind="error" message="No se pudieron cargar los fideicomisos." />
      ) : rows === null ? (
        <LoadingGrid />
      ) : rows.length === 0 ? (
        <StateBlock
          kind="empty"
          message="Aún no hay fideicomisos ingeridos. Ejecuta la sincronización de fiduciarias."
        />
      ) : (
        <Card>
          <CardHead icon={Landmark} title="Fideicomisos" subtitle={`${rows.length} fondos · ordenados por salud`} />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-2 font-medium">Fideicomiso</th>
                  <th className="py-2 px-2 font-medium">Segmento</th>
                  <th className="py-2 px-2 font-medium">Salud</th>
                  <th className="py-2 px-2 font-medium text-center">Solv.</th>
                  <th className="py-2 px-2 font-medium text-center">Liq.</th>
                  <th className="py-2 px-2 font-medium text-center">Sost.</th>
                  <th className="py-2 px-2 font-medium text-right">Activos</th>
                  <th className="py-2 px-2 font-medium text-right">Patrimonio</th>
                  <th className="py-2 px-2 font-medium text-right">Resultado</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id} className="border-b border-line/60">
                    <td className="py-2 px-2">
                      <div className="text-body font-medium truncate max-w-[260px]" title={t.name}>{t.name}</div>
                      {t.period_end && <div className="text-[10px] text-faint mono">{t.period_end}</div>}
                    </td>
                    <td className="py-2 px-2 text-muted">{SEGMENT_LABEL[t.segment ?? ""] ?? "—"}</td>
                    <td className="py-2 px-2">
                      <div className="flex items-center gap-2">
                        <HealthBadge band={t.health.band} />
                        <span className="mono text-xs text-muted tabular-nums">
                          {t.health.overall === null ? "" : fmtNum(t.health.overall, 0)}
                        </span>
                      </div>
                    </td>
                    <td className="py-2 px-2 text-center">{dimCell(t.health.solvencia)}</td>
                    <td className="py-2 px-2 text-center">{dimCell(t.health.liquidez)}</td>
                    <td className="py-2 px-2 text-center">{dimCell(t.health.sostenibilidad)}</td>
                    <td className="py-2 px-2 text-right mono text-ink tabular-nums">{mm(t.financials?.activos_totales)}</td>
                    <td className="py-2 px-2 text-right mono text-ink tabular-nums">{mm(t.financials?.patrimonio_fideicomitido)}</td>
                    <td className="py-2 px-2 text-right mono text-ink tabular-nums">{mm(t.financials?.resultado_periodo)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
