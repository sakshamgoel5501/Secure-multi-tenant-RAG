"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { queryForDoc } from "@/lib/corpus";
import { GROUPS } from "@/lib/personas";
import { usePersona } from "@/components/persona-provider";

const TENANT = "tenant-1";
const PERSONA_FOR: Record<string, string> = { eng: "t1-eng", hr: "t1-hr", fin: "t1-fin" };

type Doc = { document_id: string; groups: string[] };

export default function SecurityPage() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [docId, setDocId] = useState("");
  const [groups, setGroups] = useState<string[]>([]);
  const [original, setOriginal] = useState<string[]>([]);
  const [sees, setSees] = useState<Record<string, boolean>>({});
  const [epoch, setEpoch] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { persona } = usePersona();
  const ownGroup = persona?.admin === "group" ? persona.group : undefined;

  const checkAll = useCallback(async (id: string) => {
    const results = await Promise.all(
      GROUPS.map(async (g) => {
        const r = await fetch("/api/check", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ personaId: PERSONA_FOR[g], query: queryForDoc(id) }),
        });
        const body = await r.json().catch(() => null);
        return [g, r.ok && (body.documentIds as string[]).includes(id)] as const;
      }),
    );
    setSees(Object.fromEntries(results));
  }, []);

  const select = useCallback(
    (list: Doc[], id: string) => {
      const doc = list.find((d) => d.document_id === id);
      if (!doc) return;
      setDocId(id);
      setGroups(doc.groups);
      setOriginal(doc.groups);
      setEpoch(null);
      checkAll(id);
    },
    [checkAll],
  );

  useEffect(() => {
    (async () => {
      const r = await fetch(`/api/admin/documents?tenant=${TENANT}`);
      const body = await r.json().catch(() => null);
      if (!r.ok) return setError(body?.error ?? `Request failed (${r.status})`);
      setDocs(body.documents);
      select(body.documents, body.documents[0]?.document_id);
    })();
  }, [select]);

  async function apply(next: string[]) {
    setBusy(true);
    setError(null);
    const r = await fetch(`/api/admin/documents/${docId}/acl`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant: TENANT, groups: next }),
    });
    const body = await r.json().catch(() => null);
    if (!r.ok) setError(body?.error ?? `Save failed (${r.status})`);
    else {
      setGroups(next);
      setEpoch(body.epoch);
      await checkAll(docId);
    }
    setBusy(false);
  }

  const changed = groups.join() !== original.join();

  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Security</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Revoke a group&apos;s access to a document, then see whether each group can still find it.
          The search index is untouched: its stored chunks still list the old groups, and access is
          decided from the permission store on every request.
        </p>
      </header>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {docs.length === 0 && !error && (
        <p className="text-sm text-muted-foreground">
          {ownGroup
            ? `No documents that ${ownGroup} can read. Upload one first.`
            : "No documents yet."}
        </p>
      )}

      <Card>
        <CardContent className="space-y-5 pt-6">
          <div className="flex items-center gap-3">
            <label className="text-sm text-muted-foreground" htmlFor="doc">
              Document
            </label>
            <select
              id="doc"
              value={docId}
              onChange={(e) => select(docs, e.target.value)}
              className="rounded-md border bg-background px-2 py-1 font-mono text-xs"
            >
              {docs.map((d) => (
                <option key={d.document_id} value={d.document_id}>
                  {d.document_id}
                </option>
              ))}
            </select>
            <span className="text-xs text-muted-foreground">tenant-1 · query: {docId && queryForDoc(docId)}</span>
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
                    {sees[g] === undefined ? "…" : sees[g] ? "can find it" : "cannot find it"}
                  </span>
                  {groups.includes(g) ? (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy || g === ownGroup}
                      title={g === ownGroup ? "Group administrators keep their own group" : undefined}
                      onClick={() => apply(groups.filter((x) => x !== g))}
                    >
                      Revoke
                    </Button>
                  ) : (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => apply([...groups, g])}>
                      Grant
                    </Button>
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
    </div>
  );
}


