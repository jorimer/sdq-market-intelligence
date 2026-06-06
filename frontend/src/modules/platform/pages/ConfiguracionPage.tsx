import { Moon, Sun, SlidersHorizontal, UserCircle } from "lucide-react";
import { PageHead, Card, CardHead } from "@/shared/ui/primitives";
import { useApp, PERIODS, SCOPES, Scope } from "@/shared/context/AppContext";
import { useAuth } from "@/shared/auth/AuthContext";

export function ConfiguracionPage() {
  const { dark, toggleDark, period, setPeriod, scope, setScope } = useApp();
  const { user } = useAuth();

  return (
    <div>
      <PageHead
        eyebrow="Plataforma"
        title="Configuración"
        sub="Preferencias de la sesión. El tema, el período y el ámbito se conservan en este navegador."
      />

      <div className="grid lg:grid-cols-2 gap-5">
        {/* Apariencia */}
        <Card>
          <CardHead icon={dark ? Moon : Sun} title="Apariencia" subtitle="Tema claro u oscuro" />
          <div className="flex items-center justify-between">
            <span className="text-sm text-body">Modo {dark ? "oscuro" : "claro"}</span>
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
          <CardHead icon={SlidersHorizontal} title="Preferencias de datos" subtitle="Período y ámbito por defecto" />
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-muted mb-1">Período</label>
              <select value={period} onChange={(e) => setPeriod(e.target.value)} className="field mono">
                {PERIODS.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-muted mb-1">Ámbito</label>
              <select value={scope} onChange={(e) => setScope(e.target.value as Scope)} className="field">
                {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>
        </Card>

        {/* Cuenta */}
        <Card className="lg:col-span-2">
          <CardHead icon={UserCircle} title="Cuenta" subtitle="Sesión actual" />
          <div className="grid sm:grid-cols-3 gap-4">
            <div>
              <div className="text-xs text-muted">Nombre</div>
              <div className="text-sm text-ink mt-0.5 truncate">{user?.full_name || "—"}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Correo</div>
              <div className="text-sm text-ink mt-0.5 truncate">{user?.email || "—"}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Rol</div>
              <div className="text-sm text-ink mt-0.5 mono uppercase">{user?.role || "—"}</div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
