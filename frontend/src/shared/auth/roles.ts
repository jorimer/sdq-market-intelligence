/* Jerarquía de roles (espejo de shared/auth/models.py:ROLE_RANK).
   super_admin ⊇ admin ⊇ analyst ⊇ viewer. */
export const ROLE_RANK: Record<string, number> = {
  viewer: 0,
  analyst: 1,
  admin: 2,
  super_admin: 3,
};

/** ¿`userRole` satisface (es >= que) `required`? */
export function roleSatisfies(userRole: string | undefined, required: string): boolean {
  return (ROLE_RANK[userRole ?? ""] ?? -1) >= (ROLE_RANK[required] ?? 99);
}

export const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super admin",
  admin: "Administrador",
  analyst: "Analista",
  viewer: "Lector",
};

export const TIER_LABELS: Record<string, string> = {
  free: "Free",
  pro: "Pro",
  enterprise: "Enterprise",
};

export const ROLE_OPTIONS = ["viewer", "analyst", "admin", "super_admin"] as const;
export const TIER_OPTIONS = ["free", "pro", "enterprise"] as const;
