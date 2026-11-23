"use client";

import { useEffect, useState } from "react";
import { LoadingDots } from "@/components/loading-dots";
import { useSession } from "@/components/session-provider";
import { Card, CardContent } from "@/components/ui/card";
import { ROLE_LABEL, type Role } from "@/lib/roles";

type Need = "lifecycle" | "purge";
type Probe = { caps: Record<Need, boolean> | null; error: string | null };

export function RoleGate({
  allow,
  need,
  children,
}: {
  allow: Role[];
  need?: Need;
  children: React.ReactNode;
}) {
  const { account, loading } = useSession();
  const allowed = !!account && allow.includes(account.role);
  const wantsProbe = allowed && Boolean(need);
  const [probe, setProbe] = useState<Probe | null>(null);

  useEffect(() => {
    if (!wantsProbe) return;
    let cancelled = false;
    fetch("/api/admin/capabilities")
      .then(async (r) => ({ ok: r.ok, body: await r.json().catch(() => null) }))
      .then(({ ok, body }) => {
        if (cancelled) return;
        setProbe(ok ? { caps: body, error: null } : { caps: null, error: body?.error ?? "The admin API is unavailable." });
      })
      .catch(() => {
        if (!cancelled) setProbe({ caps: null, error: "Could not reach the frontend server." });
      });
    return () => {
      cancelled = true;
    };
  }, [wantsProbe]);

  const checking = loading || !account || (wantsProbe && probe === null);

  let problem: string | null = null;
  if (!loading && account && !allowed) {
    problem =
      account.role === "user"
        ? "This page is for administrators."
        : account.role === "platform_admin"
          ? "Platform administrators manage accounts and the platform, not tenant data."
          : `${ROLE_LABEL[account.role]}s can't use this page.`;
  } else if (allowed && need && probe) {
    if (probe.error) problem = probe.error;
    else if (!probe.caps?.[need]) {
      problem = "The running backend doesn't support this yet. Restart it with the latest code: `rag serve --jwt --admin`.";
    }
  }

  if (problem) {
    return (
      <Card className="max-w-3xl">
        <CardContent className="pt-6 text-sm">{problem}</CardContent>
      </Card>
    );
  }
  return (
    <>
      {checking && <LoadingDots label="Checking access" />}
      <div hidden={checking}>{children}</div>
    </>
  );
}

