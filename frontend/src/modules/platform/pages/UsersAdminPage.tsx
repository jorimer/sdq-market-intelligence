import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { ShieldCheck, UserPlus, Pencil, Trash2, X, KeyRound } from "lucide-react";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { useAuth } from "@/shared/auth/AuthContext";
import {
  TIER_LABELS, ROLE_OPTIONS, TIER_OPTIONS, roleSatisfies,
} from "@/shared/auth/roles";
import {
  listUsers, createUser, updateUser, resetUserPassword, deleteUser,
  type AdminUser,
} from "../usersApi";
import {
  getProductReadiness, getUserEntitlements, grantEntitlement, revokeEntitlement,
  type UserEntitlement,
} from "../api";

const ROLE_TONE: Record<string, "ok" | "warn" | "muted" | "accent"> = {
  super_admin: "warn", admin: "accent", analyst: "ok", viewer: "muted",
};

/** Etiqueta de rol localizada (fallback al key crudo). */
const roleLabel = (t: TFunction, role: string) =>
  t(`platform.users.roles.${role}`, { defaultValue: role });

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
  const { t } = useTranslation();
  const { user: me } = useAuth();
  const isSuper = me?.role === "super_admin";
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [modal, setModal] = useState<ModalState | null>(null);
  const [entUser, setEntUser] = useState<AdminUser | null>(null);
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
    if (!window.confirm(t("platform.users.confirmDelete", { email: u.email }))) return;
    try { await deleteUser(u.id); load(); }
    catch (e) { setBanner(errMsg(e, t("platform.users.deleteError"))); }
  };

  const onToggleActive = async (u: AdminUser) => {
    const active = u.is_active;
    if (!window.confirm(t(active ? "platform.users.confirmDeactivate" : "platform.users.confirmActivate", { email: u.email }))) return;
    try { await updateUser(u.id, { is_active: !active }); load(); }
    catch (e) { setBanner(errMsg(e, t(active ? "platform.users.deactivateError" : "platform.users.activateError"))); }
  };

  return (
    <div>
      <PageHead
        eyebrow={t("platform.users.eyebrow")}
        title={t("platform.users.title")}
        sub={t("platform.users.sub")}
        right={
          <button className="btn btn-primary" onClick={() => setModal({ mode: "create" })}>
            <UserPlus className="w-4 h-4" /> {t("platform.users.newUser")}
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
        <CardHead icon={ShieldCheck} title={t("platform.users.cardTitle")} subtitle={t("platform.users.cardSub")} />
        {status === "loading" && <Skeleton className="h-48" />}
        {status === "error" && <StateBlock kind="error" message={t("platform.users.loadError")} />}
        {status === "ok" && users && users.length === 0 && (
          <StateBlock kind="empty" message={t("platform.users.empty")} />
        )}
        {status === "ok" && users && users.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-faint border-b border-line">
                  <th className="py-2 pr-3 font-medium">{t("platform.users.colUser")}</th>
                  <th className="py-2 pr-3 font-medium">{t("platform.users.colRole")}</th>
                  <th className="py-2 pr-3 font-medium">{t("platform.users.colTier")}</th>
                  <th className="py-2 pr-3 font-medium">{t("platform.users.colStatus")}</th>
                  <th className="py-2 pr-3 font-medium">{t("platform.users.colCreated")}</th>
                  <th className="py-2 pr-3 font-medium text-right">{t("platform.users.colActions")}</th>
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
                        <div className="text-xs text-muted truncate max-w-[260px]">{u.email}{isSelf && ` · ${t("platform.users.self")}`}</div>
                      </td>
                      <td className="py-2.5 pr-3"><Chip tone={ROLE_TONE[u.role] ?? "muted"}>{roleLabel(t, u.role)}</Chip></td>
                      <td className="py-2.5 pr-3"><Chip tone="muted">{TIER_LABELS[u.tier] ?? u.tier}</Chip></td>
                      <td className="py-2.5 pr-3">
                        <Chip tone={u.is_active ? "ok" : "warn"}>{u.is_active ? t("platform.users.active") : t("platform.users.inactive")}</Chip>
                      </td>
                      <td className="py-2.5 pr-3 text-xs text-muted tabular-nums">{u.created_at ? u.created_at.slice(0, 10) : "—"}</td>
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            className="btn btn-ghost !py-1 !px-2 disabled:opacity-40"
                            disabled={!manage}
                            title={manage ? t("platform.users.edit") : t("platform.users.cannotManage")}
                            onClick={() => setModal({ mode: "edit", user: u })}
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          {manage && (
                            <button className="btn btn-ghost !py-1 !px-2" title={t("platform.users.entitlements.action")}
                              onClick={() => setEntUser(u)}>
                              <KeyRound className="w-3.5 h-3.5" />
                            </button>
                          )}
                          {!isSelf && manage && (
                            <button className="btn btn-ghost !py-1 !px-2" onClick={() => onToggleActive(u)}>
                              {u.is_active ? t("platform.users.deactivate") : t("platform.users.activate")}
                            </button>
                          )}
                          {isSuper && !isSelf && (
                            <button className="btn btn-ghost !py-1 !px-2 text-alert" title={t("platform.users.delete")} onClick={() => onDelete(u)}>
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

      {entUser && (
        <EntitlementsModal user={entUser} onClose={() => setEntUser(null)} t={t} />
      )}
    </div>
  );
}

/** Panel admin: acceso por-producto (compra/otorgamiento manual) de un usuario. */
function EntitlementsModal({ user, onClose, t }: {
  user: AdminUser;
  onClose: () => void;
  t: TFunction;
}) {
  const [rows, setRows] = useState<UserEntitlement[] | null>(null);
  const [sectors, setSectors] = useState<{ key: string; name: string }[]>([]);
  const [sector, setSector] = useState("");
  const [tier, setTier] = useState("insight");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = () => getUserEntitlements(user.id).then(setRows).catch(() => setRows([]));
  useEffect(() => {
    load();
    getProductReadiness()
      .then((m) => {
        const s = m.sectors.map((x) => ({ key: x.sector_key, name: x.display_name }));
        setSectors(s);
        if (s.length) setSector(s[0].key);
      })
      .catch(() => setSectors([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onGrant = async () => {
    if (!sector) return;
    setBusy(true);
    setErr(null);
    try {
      await grantEntitlement({ user_id: user.id, sector, tier, note: note.trim() || undefined });
      setNote("");
      await load();
    } catch (e) {
      setErr(errMsg(e, t("platform.users.entitlements.grantError")));
    } finally {
      setBusy(false);
    }
  };

  const onRevoke = async (id: string) => {
    setBusy(true);
    setErr(null);
    try {
      await revokeEntitlement(id);
      await load();
    } catch (e) {
      setErr(errMsg(e, t("platform.users.entitlements.grantError")));
    } finally {
      setBusy(false);
    }
  };

  const active = (rows ?? []).filter((r) => r.active);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button aria-label="Cerrar" onClick={onClose} className="absolute inset-0 bg-ink/40 backdrop-blur-sm" />
      <div className="relative w-full max-w-lg bg-surface border border-line rounded-xl shadow-pop p-5 max-h-[85vh] overflow-y-auto">
        <div className="flex items-start gap-3 mb-4">
          <div className="min-w-0 flex-1">
            <div className="text-xs text-muted truncate">{t("platform.users.entitlements.title")}</div>
            <h2 className="text-base font-semibold text-ink font-display truncate">{user.full_name}</h2>
          </div>
          <button onClick={onClose} className="btn btn-ghost shrink-0 -mr-2" aria-label="Cerrar">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-xs text-muted mb-3">{t("platform.users.entitlements.help")}</p>

        {/* Grant */}
        <div className="rounded-lg border border-line p-3 space-y-2 mb-4">
          <div className="grid grid-cols-2 gap-2">
            <Field label={t("platform.users.entitlements.sector")}>
              <select className="field" value={sector} onChange={(e) => setSector(e.target.value)}>
                {sectors.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
              </select>
            </Field>
            <Field label={t("platform.users.entitlements.tier")}>
              <select className="field" value={tier} onChange={(e) => setTier(e.target.value)}>
                <option value="pulse">Pulse</option>
                <option value="insight">Insight</option>
                <option value="deep_dive">Deep Dive</option>
              </select>
            </Field>
          </div>
          <Field label={t("platform.users.entitlements.note")}>
            <input className="field" value={note} maxLength={255} onChange={(e) => setNote(e.target.value)}
              placeholder={t("platform.users.entitlements.notePlaceholder")} />
          </Field>
          {err && <p className="text-xs text-alert" role="alert">{err}</p>}
          <button className="btn btn-primary w-full" disabled={busy || !sector} onClick={onGrant}>
            {t("platform.users.entitlements.grant")}
          </button>
        </div>

        {/* Activos */}
        <div className="text-xs font-medium text-ink mb-2">{t("platform.users.entitlements.activeTitle")}</div>
        {rows === null ? (
          <Skeleton className="h-16" />
        ) : active.length === 0 ? (
          <p className="text-xs text-faint">{t("platform.users.entitlements.empty")}</p>
        ) : (
          <ul className="space-y-1.5">
            {active.map((r) => (
              <li key={r.id} className="flex items-center gap-2 rounded-lg border border-line p-2">
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-ink truncate">{r.sector_key} · {r.tier}</div>
                  <div className="text-[11px] text-faint truncate">{r.note || r.source}</div>
                </div>
                <button className="btn btn-ghost !py-1 !px-2 text-xs text-alert shrink-0"
                  disabled={busy} onClick={() => onRevoke(r.id)}>
                  {t("platform.users.entitlements.revoke")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
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
  const { t } = useTranslation();
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
        onSaved(t("platform.users.updated", { email }));
      } else {
        await createUser({ email, password, full_name: fullName, role, tier });
        onSaved(t("platform.users.created", { email }));
      }
    } catch (e) {
      onError(errMsg(e, t("platform.users.saveError")));
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
            {editing ? t("platform.users.modalEdit") : t("platform.users.modalNew")}
          </h3>
          <button onClick={onClose} className="text-faint hover:text-ink"><X className="w-4 h-4" /></button>
        </div>
        <div className="space-y-3">
          <Field label={t("platform.users.fullName")}>
            <input className="field w-full" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label={t("platform.users.fEmail")}>
            <input className="field w-full disabled:opacity-60" type="email" value={email}
                   disabled={editing} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label={editing ? t("platform.users.newPassword") : t("platform.users.password")}>
            <input className="field w-full" type="password" value={password}
                   placeholder={editing ? t("platform.users.phKeepPassword") : t("platform.users.phMinChars")}
                   onChange={(e) => setPassword(e.target.value)} />
            {pwTooShort && <span className="text-[11px] text-alert">{t("platform.users.pwTooShort")}</span>}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("platform.users.fRole")}>
              <select className="field w-full disabled:opacity-60" value={role}
                      disabled={isSelf} title={isSelf ? t("platform.users.cannotChangeOwnRole") : ""}
                      onChange={(e) => setRole(e.target.value)}>
                {roleChoices.map((r) => (
                  <option key={r} value={r} disabled={!assignableRoles.includes(r)}>
                    {roleLabel(t, r)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("platform.users.fTier")}>
              <select className="field w-full" value={tier} onChange={(e) => setTier(e.target.value)}>
                {TIER_OPTIONS.map((opt) => <option key={opt} value={opt}>{TIER_LABELS[opt]}</option>)}
              </select>
            </Field>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn btn-ghost" onClick={onClose}>{t("platform.users.cancel")}</button>
          <button className="btn btn-primary" disabled={!canSubmit} onClick={submit}>
            {saving ? t("platform.users.saving") : editing ? t("platform.users.save") : t("platform.users.create")}
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
