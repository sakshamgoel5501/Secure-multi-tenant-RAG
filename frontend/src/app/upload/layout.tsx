import { RoleGate } from "@/components/role-gate";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <RoleGate allow={["tenant_admin","group_admin"]} need="lifecycle">{children}</RoleGate>;
}