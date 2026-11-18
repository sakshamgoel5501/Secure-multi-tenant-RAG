"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Stage = { n: number; p50: number; p95: number; max: number };
type Stats = { latency_ms: Record<string, Stage>; status: Record<string, number> };
type Dlq = { pending: number; entries: Record<string, string>[] };

function LatencyTable({ route, stats }: { route: string; stats: Stats }) {
  const rows = Object.entries(stats.latency_ms)
    .filter(([k]) => k.startsWith(`${route}:`))
    .map(([k, v]) => [k.slice(route.length + 1), v] as const)
    .sort((a, b) => (a[0] === "total" ? -1 : b[0] === "total" ? 1 : b[1].p95 - a[1].p95));
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No requests yet.</p>;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-muted-foreground">
        <tr>
          <th className="py-1 font-medium">Stage</th>
          <th className="py-1 text-right font-medium">p50 ms</th>
          <th className="py-1 text-right font-medium">p95 ms</th>
          <th className="py-1 text-right font-medium">requests</th>
        </tr>
      </thead>
      <tbody className="tabular-nums">
        {rows.map(([stage, v]) => (
          <tr key={stage} className="border-t">
            <td className={`py-1 ${stage === "total" ? "font-medium" : "text-muted-foreground"}`}>{stage}</td>
            <td className="py-1 text-right">{v.p50}</td>
            <td className="py-1 text-right">{v.p95}</td>
            <td className="py-1 text-right text-muted-foreground">{v.n}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function OperationsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [dlq, setDlq] = useState<Dlq | null>(null);
  const [dlqError, setDlqError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function poll() {
      const s = await fetch("/api/stats").catch(() => null);
      if (s?.ok) {
        setStats(await s.json());
        setError(null);
      } else setError("Backend unreachable.");
      const d = await fetch("/api/admin/dlq").catch(() => null);
      const body = await d?.json().catch(() => null);
      if (d?.ok) {
        setDlq(body);
        setDlqError(null);
      } else setDlqError(body?.error ?? "Admin API unavailable.");
    }
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  const statusEntries = stats ? Object.entries(stats.status) : [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Operations</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Live latency per pipeline stage, from the last 2,000 requests, refreshed every 5 seconds.
          Retrieval stages run partly in parallel, so they overlap and don&apos;t add up to the total.
        </p>
      </header>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {stats && (
        <div className="grid gap-4 lg:grid-cols-2">
          {["/search", "/ask"].map((route) => (
            <Card key={route}>
              <CardHeader>
                <CardTitle className="font-mono text-sm font-medium">{route}</CardTitle>
              </CardHeader>
              <CardContent>
                <LatencyTable route={route} stats={stats} />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {statusEntries.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {statusEntries.map(([k, v]) => (
            <Badge key={k} variant="outline" className="font-mono">
              {k} × {v}
            </Badge>
          ))}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">
            Ingestion dead-letter queue
            {dlq && <span className="text-muted-foreground"> · {dlq.pending} pending</span>}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {dlqError && <p className="text-muted-foreground">{dlqError}</p>}
          {dlq && dlq.entries.length === 0 && (
            <p className="text-muted-foreground">Empty. No event has failed permanently.</p>
          )}
          {dlq?.entries.map((e, i) => (
            <div key={i} className="rounded-md border p-3 font-mono text-xs">
              <div>{e.original_id} · {e.deliveries} deliveries</div>
              <div className="mt-1 text-muted-foreground">{e.error}</div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}


