import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Landmark } from "lucide-react";
import { Card, CardHead, Chip, Skeleton, StateBlock } from "@/shared/ui/primitives";
import {
  SovereignPanel,
  affirmSovereignRating,
  getSovereignPanel,
} from "../api";

/** Panel soberano multi-agencia en Datos·Gobernanza: la superficie donde se completa la
 * acción que propone la auditoría de frescura ("verificar el rating y anotar la fecha de
 * afirmación"). Solo el ancla del store sincronizado admite anotación (admin). */
export function SovereignPanelCard() {
  const { t } = useTranslation();
  const [panel, setPanel] = useState<SovereignPanel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingIso, setSavingIso] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ iso: string; ok: boolean } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setPanel(await getSovereignPanel());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onAffirm = async (iso: string) => {
    const value = drafts[iso];
    if (!value) return;
    setSavingIso(iso);
    setFeedback(null);
    try {
      await affirmSovereignRating(iso, value);
      setDrafts((d) => ({ ...d, [iso]: "" }));
      setFeedback({ iso, ok: true });
      await load();
    } catch {
      setFeedback({ iso, ok: false });
    } finally {
      setSavingIso(null);
    }
  };

  if (loading) {
    return (
      <Card>
        <CardHead icon={Landmark} title={t("datos.gobernanza.sovereign.title")} />
        <div className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-2/3" />
        </div>
      </Card>
    );
  }
  if (error || !panel) {
    return (
      <StateBlock
        kind="error"
        message={t("datos.gobernanza.sovereign.error")}
        action={
          <button onClick={load} className="btn btn-ghost">
            {t("common_retry")}
          </button>
        }
      />
    );
  }

  const meta = panel.store_fetched_at
    ? t("datos.gobernanza.sovereign.storeMeta", {
        source: panel.store_source ?? "—",
        fetched: panel.store_fetched_at,
      })
    : t("datos.gobernanza.sovereign.noStore");

  return (
    <Card>
      <CardHead
        icon={Landmark}
        title={t("datos.gobernanza.sovereign.title")}
        subtitle={t("datos.gobernanza.sovereign.subtitle", {
          anchor: panel.anchor_name,
          months: panel.stale_after_months,
        })}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted border-b border-line">
              <th scope="col" className="py-2 pr-3 font-medium">
                {t("datos.gobernanza.sovereign.colCountry")}
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                {t("datos.gobernanza.sovereign.colAgency")}
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                {t("datos.gobernanza.sovereign.colRating")}
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                {t("datos.gobernanza.sovereign.colAction")}
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                {t("datos.gobernanza.sovereign.colAffirm")}
              </th>
              <th scope="col" className="py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {panel.countries.flatMap((c) =>
              c.agencies.map((a, i) => (
                <tr key={`${c.iso}-${a.agency}`} className="border-b border-line last:border-0">
                  <td className="py-2 pr-3 font-semibold text-ink mono">
                    {i === 0 ? c.iso : ""}
                  </td>
                  <td className="py-2 pr-3 text-body">
                    {a.name}
                    {a.is_anchor && (
                      <span className="ml-1.5 text-[10px] text-faint">
                        {t("datos.gobernanza.sovereign.anchorTag")}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3 mono tabular-nums text-ink">
                    {a.rating}
                    {a.outlook ? (
                      <span className="text-faint text-xs"> · {a.outlook}</span>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3 mono tabular-nums text-body">
                    {a.action_date ?? "—"}
                  </td>
                  <td className="py-2 pr-3 mono tabular-nums text-body">
                    {a.affirm_date ?? "—"}
                  </td>
                  <td className="py-2">
                    {a.is_anchor && c.stale && (
                      <Chip tone="warn">{t("datos.gobernanza.sovereign.staleChip")}</Chip>
                    )}
                    {a.is_anchor && panel.can_annotate && c.in_store && (
                      <div className="flex items-center gap-1.5 mt-1">
                        <input
                          type="date"
                          className="field !py-1 !px-2 text-xs w-36"
                          aria-label={t("datos.gobernanza.sovereign.affirmLabel", {
                            iso: c.iso,
                          })}
                          value={drafts[c.iso] ?? ""}
                          onChange={(e) =>
                            setDrafts((d) => ({ ...d, [c.iso]: e.target.value }))
                          }
                        />
                        <button
                          className="btn btn-soft !py-1 !px-2 text-xs"
                          disabled={!drafts[c.iso] || savingIso === c.iso}
                          onClick={() => onAffirm(c.iso)}
                        >
                          {savingIso === c.iso
                            ? t("datos.gobernanza.sovereign.saving")
                            : t("datos.gobernanza.sovereign.affirmSave")}
                        </button>
                        {feedback?.iso === c.iso && (
                          <span
                            className={`text-[11px] ${feedback.ok ? "text-muted" : "text-alert"}`}
                          >
                            {feedback.ok
                              ? t("datos.gobernanza.sovereign.saved")
                              : t("datos.gobernanza.sovereign.saveError")}
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-faint mt-3">
        {meta} · {t("datos.gobernanza.sovereign.hint")}
      </p>
    </Card>
  );
}
