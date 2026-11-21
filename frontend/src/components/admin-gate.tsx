"use client";

import { useEffect, useState } from "react";
import { usePersona } from "@/components/persona-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

type Need = "admin" | "lifecycle" | "purge";
type Probe = { caps: { lifecycle: boolean; purge: boolean } | null; error: string | null };

export function AdminGate({ need = "admin", children }: { need?: Need; children: React.ReactNode }) {
  const { persona, select } = usePersona();
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

  if (!persona || !probe) return <p className="text-sm text-muted-foreground">Checking access…</p>;

  let problem: string | null = null;
  let action: React.ReactNode = null;
  if (!persona.admin) {
    problem = "This page changes documents, so it needs the Administrator identity.";
    action = (
      <Button size="sm" onClick={() => select("admin")}>
        Switch to Administrator
      </Button>
    );
  } else if (probe.error) {
    problem = probe.error;
  } else if (need !== "admin" && !probe.caps?.[need]) {
    problem =
      "The running backend doesn't support this yet. Restart it with the latest code: `rag serve --jwt --admin`.";
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
  return <>{children}</>;
}


