import { useEffect, useMemo, useState } from "react";
import { ShieldCheck, UserPlus, Pencil, Trash2, X } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { useAuth } from "@/shared/auth/AuthContext";
import {
  ROLE_LABELS, TIER_LABELS, ROLE_OPTIONS, TIER_OPTIONS, roleSatisfies,
} from "@/shared/auth/roles";
import {
  listUsers, createUser, updateUser, resetUserPassword, deleteUser,
  type AdminUser,
} from "../usersApi";

const ROLE_TONE: Record<string, "ok" | "warn" | "muted" | "accent"> = {
  super_admin: "warn", admin: "accent", analyst: "ok", viewer: "muted",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-muted">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

interface ModalState {
  mode: "create" | "edit";
  user?: AdminUser;
}

export function UsersAdminPage() {
  const { user: me } = useAuth();
  const isSuper = me?.role === "super_admin";
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [modal, setModal] = useState<ModalState | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  // Roles que el usuario actual puede ASIGNAR (espejo de la baranda del backend).
  const assignableRoles = useMemo(
    () => (isSuper ? ROLE_OPTIONS : ROLE_OPTIONS.filter((r) => r === "viewer" || r === "analyst")),
    [isSuper],
  );

  const load = () => {
    setStatus("loading");
    listUsers()
      .then((u) => { setUsers(u); setStatus("ok"); })
      .catch(() => setStatus("error"));
  };
  useEffect(load, []);

  const canManage = (target: AdminUser) =>
    isSuper || (roleSatisfies(me?.role, "admin") && !roleSatisfies(target.role, "admin"));

  const onDelete = async (u: AdminUser) => {
    if (!window.confirm(`¿Eliminar definitivamente a ${u.email}? Esta acción no se puede deshacer.`)) return;
    try { await deleteUser(u.id); load(); }
    catch (e) { setBanner(errMsg(e, "No se pudo eliminar.")); }
  };

  const onToggleActive = async (u: AdminUser) => {
    const verb = u.is_active ? "desactivar" : "activar";
    if (!window.confirm(`¿${verb[0].toUpperCase() + verb.slice(1)} a ${u.email}?`)) return;
    try { await updateUser(u.id, { is_active: !u.is_active }); load(); }
    catch (e) { setBanner(errMsg(e, `No se pudo ${verb}.`)); }
  };

  return (
    <div>
      <PageHead
        eyebrow="Administración"
        title="Usuarios y accesos"
        sub="Gestión de usuarios, roles (qué puede administrar) y tier (nivel de acceso para monetización)."
        right={
          <button className="btn btn-primary" onClick={() => setModal({ mode: "create" })}>
            <UserPlus className="w-4 h-4" /> Nuevo usuario
          </button>
        }
      />

      {banner && (
        <div className="mb-4 rounded-lg border border-line bg-subtle/40 p-3 flex items-start gap-2">
          <span className="text-sm text-body flex-1">{banner}</span>
          <button onClick={() => setBanner(null)} className="text-faint hover:text-ink"><X className="w-4 h-4" /></button>
        </div>
      )}

      <Card>
        <CardHead icon={ShieldCheck} title="Usuarios" subtitle="Rol jerárquico: super_admin ⊇ admin ⊇ analyst ⊇ viewer." />
        {status === "loading" && <Skeleton className="h-48" />}
        {status === "error" && <StateBlock kind="error" message="No se pudo cargar la lista de usuarios." />}
        {status === "ok" && users && users.length === 0 && (
          <StateBlock kind="empty" message="No hay usuarios todavía." />
        )}
        {status === "ok" && users && users.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-faint border-b border-line">
                  <th className="py-2 pr-3 font-medium">Usuario</th>
                  <th className="py-2 pr-3 font-medium">Rol</th>
                  <th className="py-2 pr-3 font-medium">Tier</th>
                  <th className="py-2 pr-3 font-medium">Estado</th>
                  <th className="py-2 pr-3 font-medium">Alta</th>
                  <th className="py-2 pr-3 font-medium text-right">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const manage = canManage(u);
                  const isSelf = u.id === me?.id;
                  return (
                    <tr key={u.id} className="border-b border-line/60 hover:bg-surface2/40">
                      <td className="py-2.5 pr-3">
                        <div className="font-medium text-ink truncate max-w-[260px]">{u.full_name}</div>
                        <div className="text-xs text-muted truncate max-w-[260px]">{u.email}{isSelf && " · vos"}</div>
                      </td>
                      <td className="py-2.5 pr-3"><Chip tone={ROLE_TONE[u.role] ?? "muted"}>{ROLE_LABELS[u.role] ?? u.role}</Chip></td>
                      <td className="py-2.5 pr-3"><Chip tone="muted">{TIER_LABELS[u.tier] ?? u.tier}</Chip></td>
                      <td className="py-2.5 pr-3">
                        <Chip tone={u.is_active ? "ok" : "warn"}>{u.is_active ? "Activo" : "Inactivo"}</Chip>
                      </td>
                      <td className="py-2.5 pr-3 text-xs text-muted tabular-nums">{u.created_at ? u.created_at.slice(0, 10) : "—"}</td>
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            className="btn btn-ghost !py-1 !px-2 disabled:opacity-40"
                            disabled={!manage}
                            title={manage ? "Editar" : "No podés administrar este usuario"}
                            onClick={() => setModal({ mode: "edit", user: u })}
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          {!isSelf && manage && (
                            <button className="btn btn-ghost !py-1 !px-2" onClick={() => onToggleActive(u)}>
                              {u.is_active ? "Desactivar" : "Activar"}
                            </button>
                          )}
                          {isSuper && !isSelf && (
                            <button className="btn btn-ghost !py-1 !px-2 text-alert" title="Eliminar" onClick={() => onDelete(u)}>
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {modal && (
        <UserModal
          state={modal}
          assignableRoles={assignableRoles as unknown as string[]}
          isSelf={modal.user?.id === me?.id}
          onClose={() => setModal(null)}
          onSaved={(msg) => { setModal(null); setBanner(msg); load(); }}
          onError={setBanner}
        />
      )}
    </div>
  );
}

function UserModal({
  state, assignableRoles, isSelf, onClose, onSaved, onError,
}: {
  state: ModalState;
  assignableRoles: string[];
  isSelf: boolean;
  onClose: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const editing = state.mode === "edit";
  const u = state.user;
  const [fullName, setFullName] = useState(u?.full_name ?? "");
  const [email, setEmail] = useState(u?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(u?.role ?? "viewer");
  const [tier, setTier] = useState(u?.tier ?? "free");
  const [saving, setSaving] = useState(false);

  // Si el rol actual del usuario no es asignable por mí (p.ej. super_admin visto por
  // un admin), igual lo muestro como opción deshabilitada para no "degradarlo" sin querer.
  const roleChoices = assignableRoles.includes(role) ? assignableRoles : [role, ...assignableRoles];

  const submit = async () => {
    setSaving(true);
    try {
      if (editing && u) {
        await updateUser(u.id, {
          full_name: fullName,
          role: isSelf ? undefined : role,
          tier,
          is_active: u.is_active,
        });
        if (password) await resetUserPassword(u.id, password);
        onSaved(`Usuario ${email} actualizado.`);
      } else {
        await createUser({ email, password, full_name: fullName, role, tier });
        onSaved(`Usuario ${email} creado.`);
      }
    } catch (e) {
      onError(errMsg(e, "No se pudo guardar el usuario."));
      setSaving(false);
    }
  };

  const pwTooShort = password.length > 0 && password.length < 8;
  const canSubmit = fullName.trim() && (editing || (email.trim() && password.length >= 8)) && !pwTooShort && !saving;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div className="card w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-display text-[15px] font-bold text-ink">
            {editing ? "Editar usuario" : "Nuevo usuario"}
          </h3>
          <button onClick={onClose} className="text-faint hover:text-ink"><X className="w-4 h-4" /></button>
        </div>
        <div className="space-y-3">
          <Field label="Nombre completo">
            <input className="field w-full" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Email">
            <input className="field w-full disabled:opacity-60" type="email" value={email}
                   disabled={editing} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label={editing ? "Nueva contraseña (opcional)" : "Contraseña"}>
            <input className="field w-full" type="password" value={password}
                   placeholder={editing ? "Dejar vacío para no cambiar" : "Mínimo 8 caracteres"}
                   onChange={(e) => setPassword(e.target.value)} />
            {pwTooShort && <span className="text-[11px] text-alert">Mínimo 8 caracteres.</span>}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Rol">
              <select className="field w-full disabled:opacity-60" value={role}
                      disabled={isSelf} title={isSelf ? "No podés cambiar tu propio rol" : ""}
                      onChange={(e) => setRole(e.target.value)}>
                {roleChoices.map((r) => (
                  <option key={r} value={r} disabled={!assignableRoles.includes(r)}>
                    {ROLE_LABELS[r] ?? r}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Tier (acceso)">
              <select className="field w-full" value={tier} onChange={(e) => setTier(e.target.value)}>
                {TIER_OPTIONS.map((t) => <option key={t} value={t}>{TIER_LABELS[t]}</option>)}
              </select>
            </Field>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" disabled={!canSubmit} onClick={submit}>
            {saving ? "Guardando…" : editing ? "Guardar" : "Crear"}
          </button>
        </div>
      </div>
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function errMsg(e: any, fallback: string): string {
  return e?.response?.data?.detail || fallback;
}
