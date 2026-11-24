import { RoleGate } from "@/components/role-gate";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <RoleGate allow={["platform_admin", "tenant_admin"]} >{children}</RoleGate>;
}

