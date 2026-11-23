"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

type Entry = {
  at: string;
  actor: string;
  role: string;
  tenant: string | null;
  action: string;
  target: string;
  detail: Record<string, unknown>;
};

export default function AuditPage() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/admin/audit?limit=200")
      .then(async (r) => ({ ok: r.ok, body: await r.json().catch(() => null) }))
      .then(({ ok, body }) => {
        if (cancelled) return;
        if (!ok) setError(body?.error ?? "Could not load the audit log.");
        else {
          setError(null);
          setEntries(body.entries);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  return (
    <div className="max-w-5xl space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Audit</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every administrative change and every denied attempt, newest first. A change is recorded
            before it is made, and is refused if it can&apos;t be recorded. Document text is never stored here.
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setTick((n) => n + 1)}>
          Refresh
        </Button>
      </header>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">When</th>
              <th className="px-3 py-2 font-medium">Who</th>
              <th className="px-3 py-2 font-medium">Tenant</th>
              <th className="px-3 py-2 font-medium">Action</th>
              <th className="px-3 py-2 font-medium">Target</th>
              <th className="px-3 py-2 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={i} className="border-b align-top last:border-0">
                <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
                  {new Date(e.at).toLocaleString()}
                </td>
                <td className="px-3 py-2 text-xs">
                  {e.actor}
                  <div className="text-muted-foreground">{e.role}</div>
                </td>
                <td className="px-3 py-2 text-xs">{e.tenant ?? "–"}</td>
                <td className={`px-3 py-2 font-mono text-xs ${e.action.startsWith("denied") ? "text-destructive" : ""}`}>
                  {e.action}
                </td>
                <td className="px-3 py-2 font-mono text-xs">{e.target || "–"}</td>
                <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                  {Object.keys(e.detail).length ? JSON.stringify(e.detail) : ""}
                </td>
              </tr>
            ))}
            {entries.length === 0 && !error && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-xs text-muted-foreground">
                  Nothing recorded yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

