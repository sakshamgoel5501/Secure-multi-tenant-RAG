"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

type Detail = {
  status: string;
  active_version: number | null;
  latest_seen_version: number;
  pending: boolean;
  searchable: boolean;
  groups: string[];
};

export function DocumentDetail({ id, tenant }: { id: string; tenant: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [title, setTitle] = useState(id);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const r = await fetch(`/api/admin/documents/${id}?tenant=${tenant}`).catch(() => null);
      const body = await r?.json().catch(() => null);
      if (cancelled) return;
      if (!r || !r.ok) {
        setError(body?.error ?? "Could not load the document.");
        return;
      }
      setError(null);
      setDetail(body);
    }
    load();
    const t = setInterval(load, 2000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [id, tenant, tick]);

  async function publish() {
    setBusy(true);
    setNote(null);
    const r = await fetch(`/api/admin/documents/${id}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant, title, text }),
    }).catch(() => null);
    const body = await r?.json().catch(() => null);
    if (!r || !r.ok) setError(body?.error ?? "Publish failed.");
    else {
      setNote(`Version ${body.version} published. It goes live once ingestion finishes.`);
      setText("");
    }
    setBusy(false);
    refresh();
  }

  async function remove() {
    if (!window.confirm("Delete this document? It disappears from search immediately.")) return;
    setBusy(true);
    const r = await fetch(`/api/admin/documents/${id}?tenant=${tenant}`, { method: "DELETE" }).catch(() => null);
    const body = await r?.json().catch(() => null);
    if (!r || !r.ok) setError(body?.error ?? "Delete failed.");
    else setNote(`Delete recorded as version ${body.version}. Publish a newer version to bring it back.`);
    setBusy(false);
    refresh();
  }

  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <Link href="/documents" className="text-xs text-muted-foreground hover:underline">← Documents</Link>
        <h1 className="mt-1 font-mono text-xl font-semibold tracking-tight">{id}</h1>
        <p className="text-sm text-muted-foreground">{tenant}</p>
      </header>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!id.startsWith("u-") && (
        <p className="rounded-md border p-3 text-xs text-muted-foreground">
          This document is part of the evaluation corpus. Changing or deleting it will change eval results.
        </p>
      )}

      {detail && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 pt-6 text-sm">
            <Badge variant={detail.status === "active" ? "secondary" : "outline"}>{detail.status}</Badge>
            <span>live version: <b className="tabular-nums">{detail.active_version ?? "none"}</b></span>
            <span>latest announced: <b className="tabular-nums">{detail.latest_seen_version}</b></span>
            {detail.pending && <Badge variant="outline">v{detail.latest_seen_version} pending</Badge>}
            <span className="text-muted-foreground">groups: {detail.groups.join(", ") || "nobody"}</span>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-3 pt-6">
          <h2 className="text-sm font-medium">Publish a new version</h2>
          <p className="text-xs text-muted-foreground">
            Document text is not stored after indexing, so type the full new text. Until the new
            version is promoted, searches keep returning the current one.
          </p>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
          />
          <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} placeholder="New text" />
          <div className="flex justify-between">
            <Button variant="outline" onClick={remove} disabled={busy}>Delete document</Button>
            <Button onClick={publish} disabled={busy || !text.trim() || !title.trim()}>Publish version</Button>
          </div>
          {note && <p className="text-xs text-muted-foreground">{note}</p>}
        </CardContent>
      </Card>
    </div>
  );
}

