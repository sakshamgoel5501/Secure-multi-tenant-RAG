"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePersona } from "@/components/persona-provider";
import { Card, CardContent } from "@/components/ui/card";
import { LoadingDots } from "@/components/loading-dots";

type Need = "admin" | "lifecycle" | "purge";
type Probe = { caps: { lifecycle: boolean; purge: boolean } | null; error: string | null };

export function AdminGate({
  need = "admin",
  tenant,
  level = "group",
  children,
}: {
  need?: Need;
  tenant?: string;
  level?: "group" | "tenant";
  children: React.ReactNode;
}) {
  const { persona } = usePersona();
  const [probe, setProbe] = useState<Probe | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/capabilities")
      .then(async (r) => ({ ok: r.ok, body: await r.json().catch(() => null) }))
      .then(({ ok, body }) => {
        if (cancelled) return;
        setProbe(
          ok
            ? { caps: body, error: null }
            : { caps: null, error: body?.error ?? "The admin API is unavailable." },
        );
      })
      .catch(() => {
        if (!cancelled) setProbe({ caps: null, error: "Could not reach the frontend server." });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const checking = !persona || !probe;

  let problem: string | null = null;
  let action: React.ReactNode = null;
  if (persona && probe) {
    if (!persona.admin) {
      problem = "This page changes documents, so it needs an administrator identity.";
      action = (
        <Link href="/identity" className="inline-block rounded-md border px-3 py-1.5 text-xs hover:bg-muted">
          Choose an identity
        </Link>
      );
    } else if (level === "tenant" && persona.admin === "group") {
      problem = "This page needs a tenant or platform administrator.";
    } else if (tenant && persona.admin !== "platform" && persona.tenant !== tenant) {
      problem = `This demo runs on ${tenant}. Use the platform administrator or the ${tenant} administrator.`;
    } else if (probe.error) {
      problem = probe.error;
    } else if (need !== "admin" && !probe.caps?.[need]) {
      problem =
        "The running backend doesn't support this yet. Restart it with the latest code: `rag serve --jwt --admin`.";
    }
  }

  if (problem) {
    return (
      <Card className="max-w-3xl">
        <CardContent className="space-y-3 pt-6 text-sm">
          <p>{problem}</p>
          {action}
        </CardContent>
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

