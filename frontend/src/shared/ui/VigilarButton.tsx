import { useEffect, useState } from "react";
import { Bell, BellOff, BellRing } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  getAlertSubscriptions,
  unwatch,
  watchSubject,
  type AlertSubscription,
} from "@/shared/api/alerts";
import { mensajeDeError } from "../../shared/api/errores";

interface Props {
  sectorKey: string;
  /** Sujeto vigilado; ausente = todo el eje (nivel Pulse). */
  subject?: string | null;
}

/**
 * Botón «Vigilar» — el punto de entrada REAL a la watchlist.
 *
 * Va junto al producto que el cliente está mirando, no en una pantalla de configuración:
 * nadie configura alertas en abstracto, las pide cuando tiene delante lo que le importa.
 *
 * Tres decisiones de comportamiento:
 *
 * 1. **Resuelve su propio estado.** Consulta las vigilancias al montarse en vez de recibirlas
 *    por props: así se puede colgar de cualquier ficha sin cablear estado en el padre.
 * 2. **El error se MUESTRA, no se traga.** Un 402 (tu plan no alcanza) y un 422 (este eje
 *    tiene sujeto único) le dicen al cliente algo accionable; un botón que no hace nada, no.
 * 3. **Sin toast.** `ToastProvider` no está montado en la app, así que `useToast()` reventaría
 *    en tiempo de ejecución. El aviso vive acá al lado del botón.
 */
export function VigilarButton({ sectorKey, subject }: Props) {
  const { t } = useTranslation();
  const target = subject ?? null;
  const [sub, setSub] = useState<AlertSubscription | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    getAlertSubscriptions()
      .then((r) => {
        if (!vivo) return;
        setSub(r.subscriptions.find(
          (s) => s.sector_key === sectorKey && (s.subject ?? null) === target) || null);
      })
      .catch(() => { /* sin watchlist legible, el botón queda en "vigilar" */ })
      .finally(() => { if (vivo) setLoaded(true); });
    return () => { vivo = false; };
  }, [sectorKey, target]);

  const onClick = async () => {
    setBusy(true);
    setMsg(null);
    try {
      if (sub) {
        await unwatch(sub.id);
        setSub(null);
      } else {
        setSub(await watchSubject(sectorKey, target));
      }
    } catch (e) {
      // El 402 trae un objeto con el upsell; el 422, una lista de validación.
      setMsg(mensajeDeError(e, t("alerts.watchError")));
    } finally {
      setBusy(false);
    }
  };

  const vigilando = Boolean(sub);
  const suspendida = Boolean(sub?.suspended_reason);
  const Icon = suspendida ? BellOff : vigilando ? BellRing : Bell;

  return (
    <div className="flex flex-col gap-1">
      <button
        onClick={onClick}
        disabled={busy || !loaded}
        title={target ? t("alerts.watchSubjectHint", { subject: target })
                      : t("alerts.watchSectorHint")}
        className={`btn text-sm disabled:opacity-40 ${vigilando ? "btn-soft" : "btn-ghost"}`}
      >
        <Icon className="w-4 h-4" />
        {vigilando ? t("alerts.watching") : t("alerts.watch")}
      </button>
      {suspendida && (
        <span className="text-[11px] text-warn">{t("alerts.suspended")}</span>
      )}
      {msg && <span className="text-[11px] text-alert max-w-[22rem]">{msg}</span>}
      {vigilando && !suspendida && sub?.sector_produce_alertas === false && (
        // La honestidad del estado, y SOLO donde corresponde: este eje todavía no tiene
        // productor enchufado al barrido, así que la vigilancia se guarda y no suena.
        // Decirlo en un eje que sí produce sería la mentira opuesta.
        <span className="text-[11px] text-faint">{t("alerts.pendingEngine")}</span>
      )}
    </div>
  );
}
