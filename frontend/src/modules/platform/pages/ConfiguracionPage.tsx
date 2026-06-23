import { useTranslation } from "react-i18next";
import { Moon, Sun, SlidersHorizontal, UserCircle } from "lucide-react";
import { PageHead, Card, CardHead, StateBlock } from "@/shared/ui/primitives";
import { useApp, SCOPES, Scope } from "@/shared/context/AppContext";
import { useAuth } from "@/shared/auth/AuthContext";
import { DataSourcesSection } from "../components/DataSourcesSection";
import { SeriesMaintenanceSection } from "../components/SeriesMaintenanceSection";

export function ConfiguracionPage() {
  const { t } = useTranslation();
  const { dark, toggleDark, period, setPeriod, periods, scope, setScope } = useApp();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <div>
      <PageHead
        eyebrow={t("platform.config.eyebrow")}
        title={t("platform.config.title")}
        sub={t("platform.config.sub")}
      />

      {/* Fuentes de datos y claves de API — solo admin */}
      <div className="mb-5 space-y-5">
        {isAdmin ? (
          <>
            <DataSourcesSection />
            <SeriesMaintenanceSection />
          </>
        ) : (
          <StateBlock
            kind="forbidden"
            message={t("platform.config.forbidden")}
          />
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        {/* Apariencia */}
        <Card>
          <CardHead icon={dark ? Moon : Sun} title={t("platform.config.appearance")} subtitle={t("platform.config.appearanceSub")} />
          <div className="flex items-center justify-between">
            <span className="text-sm text-body">{dark ? t("platform.config.modeDark") : t("platform.config.modeLight")}</span>
            <button
              onClick={toggleDark}
              role="switch"
              aria-checked={dark}
              className={`relative w-12 h-7 rounded-full transition ${dark ? "bg-accent" : "bg-surface2 border border-linestrong"}`}
            >
              <span
                className={`absolute top-1 w-5 h-5 rounded-full bg-surface shadow transition-all ${dark ? "left-6" : "left-1"}`}
              />
            </button>
          </div>
        </Card>

        {/* Preferencias de datos */}
        <Card>
          <CardHead icon={SlidersHorizontal} title={t("platform.config.dataPrefs")} subtitle={t("platform.config.dataPrefsSub")} />
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-muted mb-1">{t("platform.config.period")}</label>
              <select value={period} onChange={(e) => setPeriod(e.target.value)} className="field mono">
                {periods.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-muted mb-1">{t("platform.config.scope")}</label>
              <select value={scope} onChange={(e) => setScope(e.target.value as Scope)} className="field">
                {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>
        </Card>

        {/* Cuenta */}
        <Card className="lg:col-span-2">
          <CardHead icon={UserCircle} title={t("platform.config.account")} subtitle={t("platform.config.accountSub")} />
          <div className="grid sm:grid-cols-3 gap-4">
            <div>
              <div className="text-xs text-muted">{t("platform.config.name")}</div>
              <div className="text-sm text-ink mt-0.5 truncate">{user?.full_name || "—"}</div>
            </div>
            <div>
              <div className="text-xs text-muted">{t("platform.config.email")}</div>
              <div className="text-sm text-ink mt-0.5 truncate">{user?.email || "—"}</div>
            </div>
            <div>
              <div className="text-xs text-muted">{t("platform.config.role")}</div>
              <div className="text-sm text-ink mt-0.5 mono uppercase">{user?.role || "—"}</div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
