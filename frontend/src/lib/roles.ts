export type Role = "user" | "group_admin" | "tenant_admin" | "platform_admin";

export type Account = {
  username: string;
  role: Role;
  tenant: string | null;
  groups: string[];
  must_change_password: boolean;
};

export const GROUPS = ["eng", "hr", "fin"];

export const ROLE_LABEL: Record<Role, string> = {
  user: "User",
  group_admin: "Group administrator",
  tenant_admin: "Tenant administrator",
  platform_admin: "Platform administrator",
};

