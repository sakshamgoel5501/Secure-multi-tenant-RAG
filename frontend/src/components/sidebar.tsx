"use client";

import { Activity, FileText, Home, ListChecks, MessageSquare, ShieldCheck, Sparkles, User } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { usePersona } from "@/components/persona-provider";
import { ThemeToggle } from "@/components/theme-toggle";

const NAV = [
  { href: "/", label: "Home", icon: Home, ready: true },
  { href: "/ask", label: "Ask", icon: MessageSquare, ready: true },
  { href: "/identity", label: "Identity", icon: User, ready: true },
  { href: "/documents", label: "Documents", icon: FileText, ready: true },
  { href: "/security", label: "Security", icon: ShieldCheck, ready: true },
  { href: "/operations", label: "Operations", icon: Activity, ready: true },
  { href: "/evaluation", label: "Evaluation", icon: ListChecks, ready: true },
  { href: "/custom", label: "Your tab", icon: Sparkles, ready: false },
];

export function Sidebar() {
  const pathname = usePathname();
  const { persona } = usePersona();

  if (pathname === "/login") return null;

  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r bg-card/40">
      <Link href="/" className="px-5 py-5">
        <div className="text-lg font-semibold tracking-tight">Vault</div>
        {/* <div className="text-xs text-muted-foreground">secure retrieval</div> */}
      </Link>

      <nav className="flex-1 space-y-0.5 px-3">
        {NAV.map(({ href, label, icon: Icon, ready }) => {
          const active = pathname === href;
          const base = "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm";
          if (!ready) {
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
                active ? "bg-muted font-medium" : "text-muted-foreground hover:bg-muted/60"
              }`}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="flex items-center justify-between border-t px-4 py-3">
        <Link href="/identity" className="min-w-0">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Signed in as</div>
          <div className="truncate text-sm">{persona?.label ?? "…"}</div>
        </Link>
        <ThemeToggle />
      </div>
    </aside>
  );
}

