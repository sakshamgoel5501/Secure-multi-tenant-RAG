"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const TENANT = "tenant-1";
const QUERY = "lifecycle demo launch code";
const WORDS = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF", "HOTEL", "INDIA", "JULIET"];
const text = (n: number) => `Lifecycle demo: the launch code is ${WORDS[n % WORDS.length]}.`;

type State = {
  status: string;
  active_version: number | null;
  latest_seen_version: number;
  pending: boolean;
  searchable: boolean;
};
type Served = { version: number; text: string } | null;

const SCENARIOS = [
  ["slow_update", "Slow update (5 s)", "The new version is announced, but its work arrives 5 seconds later. Watch: it shows as pending while searches keep returning the old text, then it flips."],
  ["out_of_order", "Out-of-order events", "Version N+2 arrives before N+1. The late one must lose: the live version ends at N+2 and the stale text is never served."],
  ["late_update_after_delete", "Late update after delete", "A delete at N+2 arrives, then an update from before it. The document must stay deleted. The late chunks are written but never served (orphans)."],
] as const;

export default function LifecyclePage() {
  const [docId, setDocId] = useState<string | null>(null);
  const [state, setState] = useState<State | null>(null);
  const [served, setServed] = useState<Served>(null);
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!docId) return;
    let stop = false;
    async function poll() {
      const d = await fetch(`/api/admin/documents/${docId}?tenant=${TENANT}`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      const c = await fetch("/api/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ personaId: "t1-eng", query: QUERY }),
      })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      if (stop) return;
      setState(d);
      const hit = ((c?.hits ?? []) as { document_id: string; version: number; text: string }[]).find(
        (h) => h.document_id === docId,
      );
      setServed(hit ? { version: hit.version, text: hit.text } : null);
    }
    poll();
    const t = setInterval(poll, 1000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [docId]);

  const add = (line: string) => setLog((l) => [line, ...l].slice(0, 8));
  const next = (state?.latest_seen_version ?? 0) + 1;

  async function call(label: string, url: string, init: RequestInit) {
    setBusy(true);
    const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...init }).catch(() => null);
    const body = await r?.json().catch(() => null);
    add(r?.ok ? label : `${label} failed: ${body?.error ?? "unreachable"}`);
    setBusy(false);
    return r?.ok ? body : null;
  }

  async function create() {
    const body = await call("Created a demo document (version 1).", "/api/admin/documents", {
      method: "POST",
      body: JSON.stringify({ tenant: TENANT, title: "Lifecycle demo", text: text(0), groups: ["eng"] }),
    });
    if (body) {
      setState(null);
      setServed(null);
      setDocId(body.document_id);
    }
  }

  const publishUpdate = () =>
    call(`Published version ${next}.`, `/api/admin/documents/${docId}/versions`, {
      method: "POST",
      body: JSON.stringify({ tenant: TENANT, title: "Lifecycle demo", text: text(next - 1) }),
    });
  const remove = () =>
    call("Published a delete.", `/api/admin/documents/${docId}?tenant=${TENANT}`, { method: "DELETE" });
  const simulate = (scenario: string, label: string) =>
    call(`Ran: ${label}.`, "/api/admin/simulate", {
      method: "POST",
      body: JSON.stringify({
        tenant: TENANT,
        documentId: docId,
        scenario,
        title: "Lifecycle demo",
        text: text(next + 1),
        delay: 5,
      }),
    });

  return (
    <div className="max-w-4xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Lifecycle</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Documents change, get deleted, and their events arrive late or twice. This page makes the
          guarantees visible on a throwaway document, so the evaluation corpus stays untouched. The
          left card is the authoritative state in Postgres. The right card is what a search actually
          returns to an Engineering user.
        </p>
      </header>

      {!docId ? (
        <Button onClick={create} disabled={busy}>Create a demo document</Button>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Card>
              <CardHeader><CardTitle className="text-sm font-medium">Commit point (Postgres)</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="font-mono text-xs text-muted-foreground">{docId}</div>
                {state ? (
                  <>
                    <div className="flex items-center gap-2">
                      <Badge variant={state.status === "active" ? "secondary" : "outline"}>{state.status}</Badge>
                      {state.pending && <Badge variant="outline">v{state.latest_seen_version} pending</Badge>}
                    </div>
                    <div>live version: <b>{state.active_version ?? "none"}</b></div>
                    <div>latest announced: <b>{state.latest_seen_version}</b></div>
                  </>
                ) : (
                  <div className="text-muted-foreground">loading…</div>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-sm font-medium">What a search returns</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                {served ? (
                  <>
                    <div>version served: <b>{served.version}</b></div>
                    <p className="leading-relaxed">{served.text}</p>
                  </>
                ) : (
                  <p className="text-muted-foreground">Not found. The user sees nothing.</p>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardContent className="space-y-4 pt-6">
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={publishUpdate} disabled={busy}>Publish update</Button>
                <Button size="sm" variant="outline" onClick={remove} disabled={busy}>Delete</Button>
                <Button size="sm" variant="ghost" onClick={create} disabled={busy}>New demo document</Button>
              </div>
              <div className="space-y-3">
                {SCENARIOS.map(([id, label, blurb]) => (
                  <div key={id} className="flex items-start justify-between gap-4 rounded-lg border p-3">
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      <span className="font-medium text-foreground">{label}.</span> {blurb}
                    </p>
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => simulate(id, label)}>Run</Button>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                After a delete, &ldquo;Publish update&rdquo; brings the document back, because a newer
                version beats the tombstone.
              </p>
            </CardContent>
          </Card>

          {log.length > 0 && (
            <div className="space-y-1 text-xs text-muted-foreground">
              {log.map((l, i) => (
                <div key={i}>{l}</div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}


