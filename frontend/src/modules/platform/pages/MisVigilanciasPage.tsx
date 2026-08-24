import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Bell, BellOff, Mail, Inbox, Webhook, Trash2, ShieldAlert } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import {
  getAlertRules,
  getAlertSubscriptions,
  unwatch,
  updateAlertSubscription,
  type AlertRulesCatalog,
  type AlertSubscription,
} from "@/shared/api/alerts";
import { mensajeDeError } from "../../../shared/api/errores";

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
const CANAL_ICONO: Record<string, typeof Inbox> = {
  inapp: Inbox,
  email: Mail,
  webhook: Webhook,
};

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

  // Los canales se leen del catálogo, no se listan a mano: cada uno tiene su propio gate
  // —el correo es del despliegue, el webhook es del usuario— y hardcodearlos acá haría que
  // la pantalla ofreciera algo que el backend rechaza, o escondiera algo que ya funciona.
  const disponibles = cat?.canales_disponibles ?? [];
  const sinConfigurar = cat?.canales_no_configurados ?? [];
  // Un solo canal ⇒ no hay nada que elegir. Se decide una vez acá y no dentro del map,
  // para que el criterio no se duplique.
  const unico = disponibles.length <= 1;

  async function patch(sub: AlertSubscription, cambio: Parameters<typeof updateAlertSubscription>[1]) {
    setBusy(sub.id); setMsg(null);
    try {
      const nuevo = await updateAlertSubscription(sub.id, cambio);
      setSubs((prev) => prev.map((s) => (s.id === nuevo.id ? nuevo : s)));
    } catch (e) {
      setMsg(mensajeDeError(e, tr("alerts.saveError", "No se pudo guardar el cambio.")));
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

      {/* Cada canal ausente dice POR QUÉ, y quién lo resuelve: el correo lo habilita el
          dueño de la instalación; el webhook, el propio cliente registrando un endpoint.
          Un canal que falta sin explicación se lee como que no existe. */}
      {status === "ready" && subs.length > 0 && sinConfigurar.map((canal) => (
        <div key={canal} className="text-xs text-muted flex items-start gap-2">
          <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{tr(`alerts.unavailable.${canal}`, canal)}</span>
        </div>
      ))}

      {status === "ready" && subs.map((sub) => (
        <Card key={sub.id}>
          <CardHead icon={sub.suspended_reason ? BellOff : Bell} title={sub.sector_label} />
          <div className="p-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone="muted">
                {sub.subject
                  ? tr("alerts.subject", "Sujeto: {{s}}")
                      .replace("{{s}}", sub.subject_label || sub.subject)
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
                {disponibles.map((canal) => {
                  const Icon = CANAL_ICONO[canal] ?? Inbox;
                  // Con UN solo canal disponible, el interruptor no tiene ninguna acción
                  // posible: encenderlo ya está encendido y apagarlo deja la vigilancia
                  // muda, que el backend rechaza. Se renderiza como estado. Un control
                  // cuya única respuesta posible es un error rojo no debe existir.
                  if (unico) {
                    return (
                      <span
                        key={canal}
                        title={tr("alerts.onlyChannel",
                          "Es el único canal disponible hoy; por eso no se puede apagar.")}
                        className="inline-flex items-center gap-1.5 rounded-md bg-soft px-2 py-1 text-xs text-muted"
                      >
                        <Icon className="w-3.5 h-3.5" /> {tr(`alerts.channel.${canal}`, canal)}
                      </span>
                    );
                  }
                  return (
                    <button
                      key={canal}
                      onClick={() => toggleCanal(sub, canal)}
                      disabled={busy === sub.id}
                      className={`btn !py-1 !px-2 text-xs ${sub.channels.includes(canal) ? "btn-soft" : "btn-ghost"}`}
                    >
                      <Icon className="w-3.5 h-3.5" /> {tr(`alerts.channel.${canal}`, canal)}
                    </button>
                  );
                })}
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
