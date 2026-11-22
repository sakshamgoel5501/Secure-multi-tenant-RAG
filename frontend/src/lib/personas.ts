export type Persona = {
  id: string;
  label: string;
  tenant?: string;
  group?: string;
  admin?: "platform" | "tenant" | "group";
};

export const TENANTS = ["tenant-1", "tenant-2", "tenant-3"];
export const GROUPS = ["eng", "hr", "fin"];

const GROUP_NAMES: Record<string, string> = { eng: "Engineering", hr: "HR", fin: "Finance" };
const num = (tenant: string) => tenant.replace("tenant-", "");

export const userPersonaId = (tenant: string, group: string) => `t${num(tenant)}-${group}`;

const USERS: Persona[] = TENANTS.flatMap((tenant) =>
  GROUPS.map((group) => ({
    id: userPersonaId(tenant, group),
    tenant,
    group,
    label: `Tenant ${num(tenant)} · ${GROUP_NAMES[group]}`,
  })),
);

export const PLATFORM_ADMIN: Persona = {
  id: "admin-platform",
  label: "Platform administrator",
  admin: "platform",
};

const TENANT_ADMINS: Persona[] = TENANTS.map((tenant) => ({
  id: `admin-t${num(tenant)}`,
  tenant,
  label: `Tenant ${num(tenant)} administrator`,
  admin: "tenant" as const,
}));

const GROUP_ADMINS: Persona[] = TENANTS.flatMap((tenant) =>
  GROUPS.map((group) => ({
    id: `admin-${userPersonaId(tenant, group)}`,
    tenant,
    group,
    label: `Tenant ${num(tenant)} · ${GROUP_NAMES[group]} administrator`,
    admin: "group" as const,
  })),
);

export const PERSONAS: Persona[] = [...USERS, PLATFORM_ADMIN, ...TENANT_ADMINS, ...GROUP_ADMINS];
export const DEFAULT_PERSONA_ID = "t1-eng";

export function findPersona(id: string | undefined): Persona | undefined {
  return PERSONAS.find((p) => p.id === id);
}

/** Tenants an administrator may manage. Empty for ordinary users. */
export function allowedTenants(p: Persona | null): string[] {
  if (!p?.admin) return [];
  if (p.admin === "platform") return TENANTS;
  return p.tenant ? [p.tenant] : [];
}

