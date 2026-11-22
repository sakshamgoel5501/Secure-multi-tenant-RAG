"use client";

import Link from "next/link";
import { useState } from "react";
import { usePersona } from "@/components/persona-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { GROUPS } from "@/lib/personas";
import { useAdminTenant } from "@/lib/use-admin-tenant";

export default function UploadPage() {
  const { tenant, allowed, setTenant } = useAdminTenant();
  const { persona } = usePersona();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [groups, setGroups] = useState<string[]>(["eng"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ id: string; tenant: string; ready: boolean } | null>(null);

  const own = persona?.admin === "group" ? persona.group : undefined;
  const effective = own && !groups.includes(own) ? [...groups, own] : groups;

  async function submit() {
    if (!tenant) return;
    setBusy(true);
    setError(null);
    setResult(null);
    const r = await fetch("/api/admin/documents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant, title, text, groups: effective }),
    }).catch(() => null);
    const body = await r?.json().catch(() => null);
    if (!r || !r.ok) {
      setError(body?.error ?? "Upload failed.");
      setBusy(false);
      return;
    }
    const id: string = body.document_id;
    setResult({ id, tenant, ready: false });
    for (let i = 0; i < 20; i++) {
      await new Promise((res) => setTimeout(res, 500));
      const d = await fetch(`/api/admin/documents/${id}?tenant=${tenant}`)
        .then((x) => (x.ok ? x.json() : null))
        .catch(() => null);
      if (d?.searchable) {
        setResult({ id, tenant, ready: true });
        break;
      }
    }
    setBusy(false);
  }

  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Upload</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Add a document. The access list is written first, then an event goes through the queue to
          the ingestion worker, which chunks, embeds and indexes it, and only then makes it live.
        </p>
      </header>

      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm text-muted-foreground" htmlFor="tenant">Tenant</label>
            <select
              id="tenant"
              value={tenant ?? ""}
              onChange={(e) => setTenant(e.target.value)}
              className="rounded-md border bg-background px-2 py-1 text-sm"
            >
              {allowed.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
            <span className="ml-4 text-sm text-muted-foreground">Groups with access</span>
            {GROUPS.map((g) => (
              <button
                key={g}
                disabled={g === own}
                onClick={() => setGroups((cur) => (cur.includes(g) ? cur.filter((x) => x !== g) : [...cur, g]))}
                className={`rounded-full border px-3 py-1 text-xs disabled:opacity-60 ${
                  effective.includes(g) ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"
                }`}
              >
                {g}
              </button>
            ))}
          </div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title"
            maxLength={200}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
          />
          <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Document text" rows={8} />
          {effective.length === 0 && (
            <p className="text-xs text-muted-foreground">
              With no groups, nobody can read this document. That is a valid, fully locked state.
            </p>
          )}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{text.length.toLocaleString()} / 20,000 characters</span>
            <Button onClick={submit} disabled={busy || !title.trim() || !text.trim()}>
              {busy ? "Indexing…" : "Upload"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {result && (
        <Card>
          <CardContent className="space-y-1 pt-6 text-sm">
            <div>
              <span className="font-mono">{result.id}</span> ·{" "}
              {result.ready ? "live and searchable" : "waiting for ingestion…"}
            </div>
            <Link href={`/documents/${result.id}?tenant=${result.tenant}`} className="text-muted-foreground underline underline-offset-4">
              Open document
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

