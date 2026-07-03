import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldAlert } from "lucide-react";
import { Card, CardHead, Chip, Skeleton, StateBlock } from "@/shared/ui/primitives";
import type { Tone } from "@/shared/lib/bands";
import { getSystemAlerts, type SystemAlerts, type BankAlerts } from "../api";

const severityTone = (s: string): Tone => (s === "alta" ? "alert" : "warn");

function BankRow({ b }: { b: BankAlerts }) {
  const { t } = useTranslation();
  return (
    <div className="border-t border-line py-2.5">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{b.name}</span>
        <Chip tone={severityTone(b.max_severity)}>
          {t(`banking.ewSeverity.${b.max_severity}`, b.max_severity)}
        </Chip>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {b.alerts.map((a) => (
          <span
            key={a.code}
            title={`${a.basis} · ${a.metric}: ${a.value ?? "—"} (umbral ${a.threshold})`}
            className="cursor-help"
          >
            <Chip tone={severityTone(a.severity)}>{a.label}</Chip>
          </span>
        ))}
      </div>
    </div>
  );
}

/** System-wide early-warning alerts, anchored to the RD-2003 crisis precursors. A
 *  monitoring layer that complements the point-in-time rating — never a verdict. */
export function EarlyWarningCard() {
  const { t } = useTranslation();
  const [data, setData] = useState<SystemAlerts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    getSystemAlerts()
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
        title={t("banking.ewTitle", "Alerta temprana")}
        subtitle={t("banking.ewSubtitle", "Señales de monitoreo ancladas a la crisis 2003") + period}
      />
      <div className="mt-3">
        {loading ? (
          <Skeleton className="h-40" />
        ) : error ? (
          <StateBlock kind="error" message={t("banking.ewError", "No se pudieron cargar las alertas.")} />
        ) : !data || data.n_alerts === 0 ? (
          <StateBlock
            kind="empty"
            message={t("banking.ewEmpty", "Sin banderas activas en el sistema para el último período.")}
          />
        ) : (
          <>
            <p className="mb-1 text-[11px] leading-snug text-faint">
              {t(
                "banking.ewNote",
                "Complemento del rating (no un veredicto): precursores detectables de la crisis 2003. No detecta fraude.",
              )}
            </p>
            <div className="mb-1 text-xs text-muted">
              {t("banking.ewCount", "{{n}} alertas · {{b}} bancos", {
                n: data.n_alerts,
                b: data.banks.length,
              })}
            </div>
            <div>
              {data.banks.map((b) => (
                <BankRow key={b.bank_id} b={b} />
              ))}
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
