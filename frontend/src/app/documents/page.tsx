"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "@/components/session-provider";
import { Badge } from "@/components/ui/badge";
import { GROUPS } from "@/lib/roles";

type Doc = {
  document_id: string;
  status: string;
  active_version: number | null;
  latest_seen_version: number;
  groups: string[];
};

export default function DocumentsPage() {
  const { account } = useSession();
  const tenant = account?.tenant ?? null;
  const own = account?.role === "group_admin" ? account.groups[0] : undefined;
  const [docs, setDocs] = useState<Doc[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenant) return;
    let cancelled = false;
    fetch(`/api/admin/documents?tenant=${encodeURIComponent(tenant)}`)
      .then(async (r) => ({ ok: r.ok, status: r.status, body: await r.json().catch(() => null) }))
      .then(({ ok, status, body }) => {
        if (cancelled) return;
        if (!ok) {
          setDocs([]);
          setError(body?.error ?? `Request failed (${status})`);
        } else {
          setError(null);
          setDocs(body.documents);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tenant]);

  async function toggle(doc: Doc, group: string) {
    if (saving || !tenant) return;
    const set = new Set(doc.groups);
    if (set.has(group)) set.delete(group);
    else set.add(group);
    const next = GROUPS.filter((g) => set.has(g));

    const previous = docs;
    setDocs((ds) => ds.map((d) => (d.document_id === doc.document_id ? { ...d, groups: next } : d)));
    setSaving(doc.document_id);
    setError(null);

    const r = await fetch(`/api/admin/documents/${doc.document_id}/acl`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenant, groups: next }),
    }).catch(() => null);
    const body = await r?.json().catch(() => null);

    if (!r || !r.ok) {
      setDocs(previous);
      setError(body?.error ?? "Save failed. The change was not applied.");
    } else {
      setSaved((s) => ({ ...s, [doc.document_id]: body.epoch }));
    }
    setSaving(null);
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Documents</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {tenant ?? "…"}: which version of each document is live and which groups may read it. Click a
          group to toggle it. The change is saved immediately and applies to the next request.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {docs.length} document{docs.length === 1 ? "" : "s"}
          {own ? ` that ${own} can read` : ""}
        </p>
      </header>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">Document</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Version</th>
              <th className="px-4 py-3 font-medium">Groups with access</th>
              <th className="w-40 px-4 py-3 font-medium">Last change</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.document_id} className="h-16 border-b last:border-0">
                <td className="px-4 font-mono text-xs">
                  <Link href={`/documents/${d.document_id}?tenant=${tenant}`} className="underline-offset-4 hover:underline">
                    {d.document_id}
                  </Link>
                </td>
                <td className="px-4">
                  <Badge variant={d.status === "active" ? "secondary" : "outline"}>{d.status}</Badge>
                </td>
                <td className="px-4 tabular-nums text-muted-foreground">
                  v{d.active_version ?? "–"}
                  {d.status === "active" && d.latest_seen_version !== d.active_version && ` (v${d.latest_seen_version} pending)`}
                </td>
                <td className="px-4">
                  <div className="flex gap-1.5">
                    {GROUPS.map((g) => (
                      <button
                        key={g}
                        disabled={saving !== null || g === own}
                        title={g === own ? "Group administrators keep their own group" : undefined}
                        onClick={() => toggle(d, g)}
                        className={`rounded-full border px-3 py-1 text-xs transition-colors disabled:opacity-60 ${
                          d.groups.includes(g) ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"
                        }`}
                      >
                        {g}
                      </button>
                    ))}
                  </div>
                </td>
                <td className="w-40 px-4 text-xs text-muted-foreground">
                  {saving === d.document_id ? "saving…" : d.document_id in saved ? `saved · epoch ${saved[d.document_id]}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

