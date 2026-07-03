import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldAlert } from "lucide-react";
import { Card, CardHead, Chip, Skeleton, StateBlock } from "@/shared/ui/primitives";
import type { Tone } from "@/shared/lib/bands";
import { getPensionAlerts, type PensionSystemAlerts, type AfpAlerts } from "../api";

const severityTone = (s: string): Tone => (s === "alta" ? "alert" : "warn");

function AfpRow({ a }: { a: AfpAlerts }) {
  const { t } = useTranslation();
  return (
    <div className="border-t border-line py-2.5">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{a.name}</span>
        <Chip tone={severityTone(a.max_severity)}>
          {t(`pension.ewSeverity.${a.max_severity}`, a.max_severity)}
        </Chip>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {a.alerts.map((x) => (
          <span
            key={x.code}
            title={`${x.basis} · ${x.metric}: ${x.value ?? "—"}${x.threshold != null ? ` (umbral ${x.threshold})` : ""}`}
            className="cursor-help"
          >
            <Chip tone={severityTone(x.severity)}>{x.label}</Chip>
          </span>
        ))}
      </div>
    </div>
  );
}

/** Per-AFP watch flags (return, real return, risk, cost, solvency drop). A monitoring layer
 *  that complements the ISA — never a verdict. */
export function EarlyWarningCard() {
  const { t } = useTranslation();
  const [data, setData] = useState<PensionSystemAlerts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    getPensionAlerts()
      .then((d) => active && setData(d))
      .catch(() => active && setError(true))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const period = data?.period ? ` · ${data.period}` : "";
  return (
    <Card>
      <CardHead
        icon={ShieldAlert}
        title={t("pension.ewTitle", "Alerta temprana")}
        subtitle={t("pension.ewSubtitle", "Banderas de vigilancia por AFP") + period}
      />
      <div className="mt-3">
        {loading ? (
          <Skeleton className="h-32" />
        ) : error ? (
          <StateBlock kind="error" message={t("pension.ewError", "No se pudieron cargar las alertas.")} />
        ) : !data || data.n_alerts === 0 ? (
          <StateBlock kind="empty" message={t("pension.ewEmpty", "Sin banderas de vigilancia activas.")} />
        ) : (
          <>
            <p className="mb-1 text-[11px] leading-snug text-faint">
              {t("pension.ewNote", "Señales de monitoreo para el afiliado — complemento del ISA, no un veredicto.")}
            </p>
            <div className="mb-1 text-xs text-muted">
              {t("pension.ewCount", "{{n}} banderas · {{b}} AFP", { n: data.n_alerts, b: data.afps.length })}
            </div>
            <div>
              {data.afps.map((a) => (
                <AfpRow key={a.slug} a={a} />
              ))}
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
