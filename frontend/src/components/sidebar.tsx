"use client";

import {
  Activity, FileText, GitBranch, Home, ListChecks, LogOut, MessageSquare, ScrollText,
  ShieldCheck, Sparkles, Upload, User, Users, type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "@/components/session-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { ROLE_LABEL, type Role } from "@/lib/roles";

const TENANT_ADMINS: Role[] = ["tenant_admin", "group_admin"];

const NAV: { href: string; label: string; icon: LucideIcon; roles: Role[] | "all"; ready?: boolean }[] = [
  { href: "/", label: "Home", icon: Home, roles: "all" },
  { href: "/ask", label: "Ask", icon: MessageSquare, roles: ["user"] },
  { href: "/documents", label: "Documents", icon: FileText, roles: TENANT_ADMINS },
  { href: "/upload", label: "Upload", icon: Upload, roles: TENANT_ADMINS },
  { href: "/lifecycle", label: "Lifecycle", icon: GitBranch, roles: TENANT_ADMINS },
  { href: "/security", label: "Security", icon: ShieldCheck, roles: TENANT_ADMINS },
  { href: "/users", label: "Users", icon: Users, roles: ["platform_admin"] },
  { href: "/operations", label: "Operations", icon: Activity, roles: ["platform_admin"] },
  { href: "/evaluation", label: "Evaluation", icon: ListChecks, roles: ["platform_admin"] },
  { href: "/audit", label: "Audit", icon: ScrollText, roles: ["tenant_admin", "platform_admin"] },
  { href: "/account", label: "Account", icon: User, roles: "all" },
  { href: "/custom", label: "Your tab", icon: Sparkles, roles: "all", ready: false },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { account, signOut } = useSession();

  if (pathname === "/login") return null;

  const visible = NAV.filter((n) => account && (n.roles === "all" || n.roles.includes(account.role)));

  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r bg-card/40">
      <Link href="/" className="px-5 py-5">
        <div className="text-sm font-semibold tracking-tight">Vault</div>
        <div className="text-xs text-muted-foreground">secure retrieval</div>
      </Link>

      <nav className="flex-1 space-y-0.5 px-3">
        {visible.map(({ href, label, icon: Icon, ready }) => {
          const base = "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm";
          if (ready === false) {
            return (
              <div key={href} className={`${base} cursor-not-allowed text-muted-foreground/50`}>
                <Icon className="size-4" />
                {label}
                <span className="ml-auto text-[10px] uppercase tracking-wide">soon</span>
              </div>
            );
          }
          return (
            <Link
              key={href}
              href={href}
              className={`${base} ${
                pathname === href ? "bg-muted font-medium" : "text-muted-foreground hover:bg-muted/60"
              }`}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="flex items-center justify-between border-t px-4 py-3">
        <Link href="/account" className="min-w-0">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Signed in as</div>
          <div className="truncate text-sm">{account?.username ?? "…"}</div>
          {account && (
            <div className="truncate text-[11px] text-muted-foreground">
              {ROLE_LABEL[account.role]}
              {account.tenant ? ` · ${account.tenant}` : ""}
            </div>
          )}
        </Link>
        <div className="flex">
          <ThemeToggle />
          <Button
            variant="ghost"
            size="icon"
            aria-label="Sign out"
            onClick={async () => {
              await signOut();
              router.replace("/login");
            }}
          >
            <LogOut className="size-4" />
          </Button>
        </div>
      </div>
    </aside>
  );
}

