"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useSession } from "@/components/session-provider";

type Detail = {
  status: string;
  active_version: number | null;
  latest_seen_version: number;
  pending: boolean;
  searchable: boolean;
  groups: string[];
};
type Footprint = {
  state: string | null;
  has_acl: boolean;
  chunks: Record<string, Record<string, number>>;
  events: number;
  content_left: boolean;
  files?: { version: number; kind: string; bytes: number }[];
};

function chunkText(v: Record<string, number> | undefined) {
  const parts = Object.entries(v ?? {}).map(([ver, n]) => `v${ver}: ${n} chunk${n === 1 ? "" : "s"}`);
  return parts.length ? parts.join(", ") : "none";
}

export function DocumentDetail({ id, tenant }: { id: string; tenant: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [footprint, setFootprint] = useState<Footprint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [title, setTitle] = useState(id);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const { account } = useSession();
  const [file, setFile] = useState<File | null>(null);

  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [d, f] = await Promise.all([
        fetch(`/api/admin/documents/${id}?tenant=${tenant}`).catch(() => null),
        fetch(`/api/admin/documents/${id}/footprint?tenant=${tenant}`).catch(() => null),
      ]);
      const detailBody = await d?.json().catch(() => null);
      const footBody = await f?.json().catch(() => null);
      if (cancelled) return;
      if (!d || !d.ok) {
        setError(detailBody?.error ?? "Could not load the document.");
        return;
      }
      setError(null);
      setDetail(detailBody);
      setFootprint(f?.ok ? footBody : null);
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
    let r: Response | null;
    if (file) {
      const form = new FormData();
      form.set("file", file);
      form.set("tenant_id", tenant);
      form.set("document_id", id);
      form.set("title", title);
      r = await fetch("/api/upload", { method: "POST", body: form }).catch(() => null);
    } else {
      r = await fetch(`/api/admin/documents/${id}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenant, title, text }),
      }).catch(() => null);
    }
    const body = await r?.json().catch(() => null);
    if (!r || !r.ok) setError(body?.error ?? "Publish failed.");
    else {
      setNote(`Version ${body.version} published. It goes live once ingestion finishes.`);
      setText("");
      setFile(null);
    }
    setBusy(false);
    refresh();
  }

  async function remove() {
    if (!window.confirm("Delete this document? It disappears from search immediately. Stored copies remain until you purge.")) return;
    setBusy(true);
    const r = await fetch(`/api/admin/documents/${id}?tenant=${tenant}`, { method: "DELETE" }).catch(() => null);
    const body = await r?.json().catch(() => null);
    if (!r || !r.ok) setError(body?.error ?? "Delete failed.");
    else setNote(`Delete recorded as version ${body.version}. Stored copies remain until you purge.`);
    setBusy(false);
    refresh();
  }

  async function purge() {
    if (!window.confirm("Purge every stored copy of this document (chunks, access list, queue events)? This cannot be undone.")) return;
    setBusy(true);
    const r = await fetch(`/api/admin/documents/${id}/purge?tenant=${tenant}`, { method: "POST" }).catch(() => null);
    const body = await r?.json().catch(() => null);
    if (!r || !r.ok) setError(body?.error ?? "Purge failed.");
    else {
      const c = body.chunks_deleted as Record<string, number>;
      setNote(
        `Purged: ${Object.values(c).reduce((a, b) => a + b, 0)} chunks, ${body.events_deleted} queue events` +
          `${body.acl_removed ? ", the access list" : ""}. A content-free tombstone is kept so old events cannot bring it back.` +
          `${body.blobs_deleted ?? 0} stored files`,
      );
    }
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
          This document is part of the evaluation corpus. Changing, deleting or purging it will change eval results.
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

      {footprint && (
        <Card>
          <CardContent className="space-y-3 pt-6 text-sm">
            <div className="flex items-center justify-between">
              <h2 className="font-medium">Where this document is stored</h2>
              <Badge variant={footprint.content_left ? "outline" : "secondary"}>
                {footprint.content_left ? "content still stored" : "no content left"}
              </Badge>
            </div>
            <dl className="grid grid-cols-[10rem_1fr] gap-y-1.5 text-xs">
              <dt className="text-muted-foreground">Dense index</dt>
              <dd>{chunkText(footprint.chunks.dense)}</dd>
              <dt className="text-muted-foreground">Keyword index</dt>
              <dd>{chunkText(footprint.chunks.lexical)}</dd>
              <dt className="text-muted-foreground">Access list</dt>
              <dd>{footprint.has_acl ? "present" : "removed"}</dd>
              <dt className="text-muted-foreground">Queue events (with text)</dt>
              <dt className="text-muted-foreground">Stored files</dt>
              <dd>
                {footprint.files?.length
                  ? footprint.files.map((f) => `v${f.version} ${f.kind} (${f.bytes} B)`).join(", ")
                  : "none"}
              </dd>
              <dd>{footprint.events}</dd>
              <dt className="text-muted-foreground">State row</dt>
              <dd>{footprint.state ?? "none"} (ids and version numbers only, no text)</dd>
            </dl>
            <div className="flex justify-end">
              <Button 
                variant="outline" 
                size="sm" onClick={purge} 
                disabled={busy || !footprint.content_left || account?.role === "group_admin"}
                title="Only tenant or platform administrators can purge"
              >
                Purge all stored copies
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-3 pt-6">
          <h2 className="text-sm font-medium">Publish a new version</h2>
          <p className="text-xs text-muted-foreground">
            The original text is not kept, so type the full new text. Until the new version is
            promoted, searches keep returning the current one.
          </p>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
          />
          <input type="file" accept=".pdf,.docx,.txt,.md,.markdown"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-xs text-muted-foreground" />
          <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} placeholder="New text" />
          <div className="flex justify-between">
            <Button variant="outline" onClick={remove} disabled={busy}>Delete document</Button>
            <Button onClick={publish} disabled={busy || (!file && !text.trim()) || !title.trim()}>Publish version</Button>
          </div>
          {note && <p className="text-xs text-muted-foreground">{note}</p>}
        </CardContent>
      </Card>
    </div>
  );
}


