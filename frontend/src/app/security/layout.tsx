import { AdminGate } from "@/components/admin-gate";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <AdminGate need="admin" tenant="tenant-1">
      {children}
    </AdminGate>
  );
}
