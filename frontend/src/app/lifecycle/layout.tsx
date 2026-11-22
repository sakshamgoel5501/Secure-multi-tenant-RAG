import { AdminGate } from "@/components/admin-gate";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <AdminGate need="lifecycle" tenant="tenant-1" level="tenant">
      {children}
    </AdminGate>
  );
}

