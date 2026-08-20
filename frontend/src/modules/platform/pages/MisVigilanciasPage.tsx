import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Bell, BellOff, Mail, Inbox, Trash2, ShieldAlert } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import {
  getAlertRules,
  getAlertSubscriptions,
  unwatch,
  updateAlertSubscription,
  type AlertRulesCatalog,
  type AlertSubscription,
} from "@/shared/api/alerts";

/**
 * «Mis vigilancias» — dónde el cliente elige POR DÓNDE y CADA CUÁNTO se entera.
 *
 * El botón «Vigilar» del catálogo crea la vigilancia con lo mínimo (buzón in-app, inmediato).
 * Esta pantalla existe porque sin ella el correo estaría implementado y sería inalcanzable:
 * un canal que el cliente no puede activar es un canal que no existe.
 *
 * Lo que la pantalla declara y no esconde:
 * - el canal `email` **no aparece** si esta instalación no tiene SMTP configurado, y se dice
 *   por qué en vez de mostrar una casilla que no haría nada;
 * - una vigilancia suspendida muestra su motivo;
 * - un eje sin productor de señales lo dice, en vez de parecer activo.
 */
export function MisVigilanciasPage() {
  const { t } = useTranslation();
  const tr = (k: string, d: string) => t(k, d) as string;
  const [subs, setSubs] = useState<AlertSubscription[]>([]);
  const [cat, setCat] = useState<AlertRulesCatalog | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const reload = () => {
    Promise.all([getAlertSubscriptions(), getAlertRules()])
      .then(([s, c]) => { setSubs(s.subscriptions); setCat(c); setStatus("ready"); })
      .catch(() => setStatus("error"));
  };
  useEffect(reload, []);

  const emailDisponible = Boolean(cat?.canales_disponibles.includes("email"));
  const emailSinConfigurar = Boolean(cat?.canales_no_configurados?.includes("email"));

  async function patch(sub: AlertSubscription, cambio: Parameters<typeof updateAlertSubscription>[1]) {
    setBusy(sub.id); setMsg(null);
    try {
      const nuevo = await updateAlertSubscription(sub.id, cambio);
      setSubs((prev) => prev.map((s) => (s.id === nuevo.id ? nuevo : s)));
    } catch (e) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const detail = (e as any)?.response?.data?.detail;
      setMsg(typeof detail === "string" ? detail : tr("alerts.saveError", "No se pudo guardar el cambio."));
    } finally { setBusy(null); }
  }

  async function quitar(sub: AlertSubscription) {
    setBusy(sub.id);
    try { await unwatch(sub.id); setSubs((prev) => prev.filter((s) => s.id !== sub.id)); }
    finally { setBusy(null); }
  }

  function toggleCanal(sub: AlertSubscription, canal: string) {
    const tiene = sub.channels.includes(canal);
    const nuevos = tiene ? sub.channels.filter((c) => c !== canal) : [...sub.channels, canal];
    // Sin ningún canal la vigilancia queda muda: el backend lo rechaza, pero avisarlo acá
    // evita el viaje y explica por qué no se puede.
    if (nuevos.length === 0) {
      setMsg(tr("alerts.needChannel", "Dejá al menos un canal, o dá de baja la vigilancia."));
      return;
    }
    patch(sub, { channels: nuevos });
  }

  return (
    <div className="space-y-6">
      <PageHead
        eyebrow={tr("alerts.page.eyebrow", "ALERTAS")}
        title={tr("alerts.page.title", "Mis vigilancias")}
        sub={tr("alerts.page.sub",
          "Qué vigilás, por dónde te avisamos y cada cuánto. Las señales se evalúan sobre el panel, no sobre documentos.")}
      />

      {status === "loading" && <Skeleton />}
      {status === "error" && (
        <StateBlock kind="error" message={tr("alerts.loadError", "No se pudieron cargar tus vigilancias.")} />
      )}

      {status === "ready" && subs.length === 0 && (
        <StateBlock
          kind="empty"
          message={tr("alerts.empty",
            "Todavía no vigilás nada. Abrí un producto del catálogo y usá «Vigilar».")}
        />
      )}

      {msg && <div className="text-xs text-alert">{msg}</div>}

      {status === "ready" && emailSinConfigurar && subs.length > 0 && (
        <div className="text-xs text-muted flex items-start gap-2">
          <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {tr("alerts.emailUnavailable",
              "El aviso por correo no está configurado en esta instalación, así que solo se ofrece el buzón de la plataforma.")}
          </span>
        </div>
      )}

      {status === "ready" && subs.map((sub) => (
        <Card key={sub.id}>
          <CardHead icon={sub.suspended_reason ? BellOff : Bell} title={sub.sector_label} />
          <div className="p-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone="muted">
                {sub.subject
                  ? tr("alerts.subject", "Sujeto: {{s}}").replace("{{s}}", sub.subject)
                  : tr("alerts.wholeAxis", "Todo el eje")}
              </Chip>
              <Chip tone="muted">{sub.tier_requerido}</Chip>
              {!sub.sector_produce_alertas && (
                <Chip tone="warn">{tr("alerts.noProducer", "Sin señales todavía")}</Chip>
              )}
              {sub.suspended_reason && (
                <Chip tone="warn">{tr("alerts.suspended", "Suspendida")}</Chip>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">{tr("alerts.channels", "Canales")}</span>
                <button
                  onClick={() => toggleCanal(sub, "inapp")}
                  disabled={busy === sub.id}
                  className={`btn !py-1 !px-2 text-xs ${sub.channels.includes("inapp") ? "btn-soft" : "btn-ghost"}`}
                >
                  <Inbox className="w-3.5 h-3.5" /> {tr("alerts.channel.inapp", "Plataforma")}
                </button>
                {emailDisponible && (
                  <button
                    onClick={() => toggleCanal(sub, "email")}
                    disabled={busy === sub.id}
                    className={`btn !py-1 !px-2 text-xs ${sub.channels.includes("email") ? "btn-soft" : "btn-ghost"}`}
                  >
                    <Mail className="w-3.5 h-3.5" /> {tr("alerts.channel.email", "Correo")}
                  </button>
                )}
              </div>

              <label className="flex items-center gap-2 text-xs text-muted">
                {tr("alerts.cadence", "Ritmo")}
                <select
                  value={sub.digest}
                  disabled={busy === sub.id}
                  onChange={(e) => patch(sub, { digest: e.target.value })}
                  className="field !py-1 text-xs"
                >
                  {(cat?.digests || []).map((d) => (
                    <option key={d} value={d}>{tr(`alerts.digest.${d}`, d)}</option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-2 text-xs text-muted">
                {tr("alerts.minSeverity", "Desde severidad")}
                <select
                  value={sub.min_severity}
                  disabled={busy === sub.id}
                  onChange={(e) => patch(sub, { min_severity: e.target.value })}
                  className="field !py-1 text-xs"
                >
                  {(cat?.severidades || []).map((s) => (
                    <option key={s} value={s}>{tr(`alerts.severity.${s}`, s)}</option>
                  ))}
                </select>
              </label>

              <button
                onClick={() => quitar(sub)}
                disabled={busy === sub.id}
                className="btn btn-ghost !py-1 !px-2 text-xs ml-auto"
              >
                <Trash2 className="w-3.5 h-3.5" /> {tr("alerts.remove", "Dejar de vigilar")}
              </button>
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

export default MisVigilanciasPage;
