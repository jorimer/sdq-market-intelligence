import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Bell, CheckCheck } from "lucide-react";
import {
  AppNotification,
  getNotifications,
  getUnreadCount,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/shared/api/notifications";

const POLL_MS = 60_000; // refresco del contador de no-leídas

/** Campana de notificaciones del header: contador de no-leídas + panel desplegable.
 * Lee el buzón in-app del usuario (gateado/aislado por el backend). */
export function NotificationsBell() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  const refreshCount = useCallback(async () => {
    try {
      setUnread(await getUnreadCount());
    } catch {
      // silencioso: un fallo de contador no debe ensuciar el header
    }
  }, []);

  // Contador al montar + polling.
  useEffect(() => {
    refreshCount();
    const id = window.setInterval(refreshCount, POLL_MS);
    return () => window.clearInterval(id);
  }, [refreshCount]);

  // Cerrar al hacer click afuera.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const loadList = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const res = await getNotifications();
      setItems(res.notifications);
      setUnread(res.unread);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) loadList();
  };

  // Solo rutas internas de la SPA: cualquier otra cosa (absoluta, protocolo) se ignora.
  const internalPath = (n: AppNotification) =>
    n.action_url && n.action_url.startsWith("/") && !n.action_url.startsWith("//")
      ? n.action_url
      : null;

  const onItemClick = async (n: AppNotification) => {
    const to = internalPath(n);
    if (to) {
      setOpen(false);
      navigate(to);
    }
    if (n.read) return;
    setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
    setUnread((u) => Math.max(0, u - 1));
    try {
      await markNotificationRead(n.id);
    } catch {
      refreshCount(); // reconciliar si falló
    }
  };

  const onMarkAll = async () => {
    setItems((prev) => prev.map((x) => ({ ...x, read: true })));
    setUnread(0);
    try {
      await markAllNotificationsRead();
    } catch {
      refreshCount();
    }
  };

  const fmt = (iso: string | null) =>
    iso
      ? new Date(iso).toLocaleString(i18n.language, {
          dateStyle: "medium",
          timeStyle: "short",
        })
      : "";

  return (
    <div ref={wrapRef} className="relative shrink-0">
      <button
        onClick={toggle}
        className="relative grid place-items-center w-9 h-9 rounded-[10px] text-muted hover:bg-surface2 hover:text-ink transition"
        title={t("notifications.title")}
        aria-label={t("notifications.title")}
      >
        <Bell size={18} />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 grid place-items-center rounded-full bg-accent text-accent-ink text-[10px] font-bold tabular-nums">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 max-w-[calc(100vw-2rem)] card !p-0 shadow-pop z-50 overflow-hidden">
          <div className="flex items-center justify-between px-3 h-11 border-b border-line">
            <span className="text-sm font-semibold text-ink truncate">
              {t("notifications.title")}
            </span>
            {items.some((n) => !n.read) && (
              <button
                onClick={onMarkAll}
                className="shrink-0 flex items-center gap-1 text-xs text-muted hover:text-ink transition"
                title={t("notifications.markAll")}
              >
                <CheckCheck size={13} />
                {t("notifications.markAll")}
              </button>
            )}
          </div>

          <div className="max-h-[60vh] overflow-y-auto">
            {loading ? (
              <div className="px-3 py-6 text-center text-sm text-muted">
                {t("notifications.loading")}
              </div>
            ) : error ? (
              <div className="px-3 py-6 text-center text-sm text-alert">
                {t("notifications.error")}
              </div>
            ) : items.length === 0 ? (
              <div className="px-3 py-8 text-center text-sm text-muted">
                {t("notifications.empty")}
              </div>
            ) : (
              <ul>
                {items.map((n) => (
                  <li key={n.id}>
                    <button
                      onClick={() => onItemClick(n)}
                      className={`w-full text-left px-3 py-2.5 border-b border-line last:border-0 hover:bg-surface2 transition ${
                        n.read ? "" : "bg-surface2/50"
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        {!n.read && (
                          <span className="mt-1.5 shrink-0 w-1.5 h-1.5 rounded-full bg-accent" />
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-semibold text-ink truncate">
                            {n.title}
                          </div>
                          {n.body && (
                            <div className="text-xs text-body mt-0.5">{n.body}</div>
                          )}
                          <div className="flex items-center justify-between gap-2 mt-1">
                            <span className="text-[10px] text-faint mono">
                              {fmt(n.created_at)}
                            </span>
                            {internalPath(n) && (
                              <span className="shrink-0 flex items-center gap-0.5 text-[10px] font-semibold text-accent">
                                {t("notifications.view")}
                                <ArrowRight size={10} />
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
