"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/session-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { isCorpusDoc, queryForDoc } from "@/lib/corpus";
import { GROUPS } from "@/lib/roles";

type Doc = { document_id: string; groups: string[] };

export default function SecurityPage() {
  const { account } = useSession();
  const tenant = account?.tenant ?? null;
  const own = account?.role === "group_admin" ? account.groups[0] : undefined;
  const [docs, setDocs] = useState<Doc[]>([]);
  const [docId, setDocId] = useState("");
  const [groups, setGroups] = useState<string[]>([]);
  const [original, setOriginal] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [sees, setSees] = useState<Record<string, boolean | null>>({});
  const [epoch, setEpoch] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkAll = useCallback(
    async (id: string, q: string) => {
      if (!tenant || !id || !q.trim()) return setSees({});
      const results = await Promise.all(
        GROUPS.map(async (g) => {
          const r = await fetch(`/api/admin/documents/${id}/probe`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenant_id: tenant, group: g, query: q }),
          }).catch(() => null);
          const body = await r?.json().catch(() => null);
          return [g, r?.ok ? Boolean(body?.found) : null] as const;
        }),
      );
      setSees(Object.fromEntries(results));
    },
    [tenant],
  );

  const select = useCallback(
    (list: Doc[], id: string) => {
      const doc = list.find((d) => d.document_id === id);
      if (!doc) return;
      const q = isCorpusDoc(id) ? queryForDoc(id) : "";
      setDocId(id);
      setGroups(doc.groups);
      setOriginal(doc.groups);
      setEpoch(null);
      setQuery(q);
      setSees({});
      checkAll(id, q);
    },
    [checkAll],
  );

  useEffect(() => {
    if (!tenant) return;
    let cancelled = false;
    fetch(`/api/admin/documents?tenant=${encodeURIComponent(tenant)}`)
      .then(async (r) => ({ ok: r.ok, body: await r.json().catch(() => null) }))
      .then(({ ok, body }) => {
        if (cancelled) return;
        if (!ok) return setError(body?.error ?? "Could not load documents.");
        setDocs(body.documents);
        if (body.documents[0]) select(body.documents, body.documents[0].document_id);
      });
    return () => {
      cancelled = true;
    };
  }, [tenant, select]);

  async function apply(next: string[]) {
    setBusy(true);
    setError(null);
    const r = await fetch(`/api/admin/documents/${docId}/acl`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenant, groups: next }),
    }).catch(() => null);
    const body = await r?.json().catch(() => null);
    if (!r || !r.ok) setError(body?.error ?? "Save failed.");
    else {
      setGroups(next);
      setEpoch(body.epoch);
      await checkAll(docId, query);
    }
    setBusy(false);
  }

  const changed = groups.join() !== original.join();
  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Security</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Revoke a group&apos;s access to a document, then see whether that group can still find it. The check
          runs the real search path as that group and reports only yes or no. The search index is untouched:
          access is decided from the permission store on every request.
        </p>
      </header>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {docs.length === 0 && !error && (
        <p className="text-sm text-muted-foreground">
          {own ? `No documents that ${own} can read. Upload one first.` : "No documents yet."}
        </p>
      )}

      {docs.length > 0 && (
        <Card>
          <CardContent className="space-y-5 pt-6">
            <div className="flex flex-wrap items-center gap-3">
              <label className="text-sm text-muted-foreground" htmlFor="doc">Document</label>
              <select id="doc" value={docId} onChange={(e) => select(docs, e.target.value)}
                className="rounded-md border bg-background px-2 py-1 font-mono text-xs">
                {docs.map((d) => <option key={d.document_id} value={d.document_id}>{d.document_id}</option>)}
              </select>
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="A phrase from the document"
                className="min-w-56 flex-1 rounded-md border bg-background px-2 py-1 text-xs" />
              <Button size="sm" variant="outline" onClick={() => checkAll(docId, query)} disabled={!query.trim()}>Check</Button>
            </div>

            <div className="divide-y rounded-lg border">
              {GROUPS.map((g) => (
                <div key={g} className="flex items-center justify-between px-4 py-3">
                  <div className="flex items-center gap-3">
                    <span className="w-10 text-sm font-medium">{g}</span>
                    <Badge variant="outline">{groups.includes(g) ? "in ACL" : "not in ACL"}</Badge>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className={`text-sm ${sees[g] ? "" : "text-muted-foreground"}`}>
                      {!query.trim() ? "enter a phrase" : sees[g] === undefined ? "…" : sees[g] === null ? "n/a" : sees[g] ? "can find it" : "cannot find it"}
                    </span>
                    {groups.includes(g) ? (
                      <Button size="sm" variant="outline" disabled={busy || g === own}
                        title={g === own ? "Group administrators keep their own group" : undefined}
                        onClick={() => apply(groups.filter((x) => x !== g))}>
                        Revoke
                      </Button>
                    ) : (
                      <Button size="sm" variant="ghost" disabled={busy} onClick={() => apply([...groups, g])}>Grant</Button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{epoch !== null ? `Last change committed at policy epoch ${epoch}.` : "No change made yet."}</span>
              <Button size="sm" variant="ghost" disabled={busy || !changed} onClick={() => apply(original)}>
                Restore original groups
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

