"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { GROUPS } from "@/lib/roles";

const MAX = 10 * 1000 * 1000;

export default function UploadPage() {
  const { account } = useSession();
  const tenant = account?.tenant ?? null;
  const own = account?.role === "group_admin" ? account.groups[0] : undefined;
  const [mode, setMode] = useState<"paste" | "file">("paste");
  const [filesOk, setFilesOk] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ id: string; ready: boolean } | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const groups = own && !picked.includes(own) ? [...picked, own] : picked;

  useEffect(() => {
    let cancelled = false;
    fetch("/api/admin/capabilities")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (!cancelled) setFilesOk(Boolean(b?.files));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  function choose(f: File | null) {
    setError(null);
    if (f && f.size > MAX) return setError("The file is too large (limit 10 MB).");
    setFile(f);
    if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  }

  async function submit() {
    if (!tenant) return;
    setBusy(true);
    setError(null);
    setResult(null);
    let r: Response | null;
    if (mode === "file" && file) {
      const form = new FormData();
      form.set("file", file);
      form.set("tenant_id", tenant);
      form.set("title", title);
      form.set("groups", groups.join(","));
      r = await fetch("/api/upload", { method: "POST", body: form }).catch(() => null);
    } else {
      r = await fetch("/api/admin/documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenant, title, text, groups }),
      }).catch(() => null);
    }
    const body = await r?.json().catch(() => null);
    if (!r || !r.ok) {
      setError(body?.error ?? "Upload failed.");
      setBusy(false);
      return;
    }
    const id: string = body.document_id;
    setResult({ id, ready: false });
    for (let i = 0; i < 40; i++) {
      await new Promise((res) => setTimeout(res, 500));
      const d = await fetch(`/api/admin/documents/${id}?tenant=${tenant}`)
        .then((x) => (x.ok ? x.json() : null))
        .catch(() => null);
      if (d?.searchable) {
        setResult({ id, ready: true });
        break;
      }
    }
    setBusy(false);
  }

  const ready = title.trim() && (mode === "file" ? file : text.trim());
  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Upload</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Add a document to {tenant ?? "…"}. The access list is written first, then an event goes through the queue
          to the ingestion worker, which chunks, embeds and indexes it, and only then makes it live.
        </p>
      </header>

      <Card>
        <CardContent className="space-y-4 pt-6">
          {filesOk && (
            <div className="flex gap-2">
              {(["paste", "file"] as const).map((m) => (
                <Button key={m} size="sm" variant={mode === m ? "default" : "outline"} onClick={() => setMode(m)}>
                  {m === "paste" ? "Paste text" : "Upload a file"}
                </Button>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-muted-foreground">Groups with access</span>
            {GROUPS.map((g) => (
              <button
                key={g}
                disabled={g === own}
                onClick={() => setPicked((cur) => (cur.includes(g) ? cur.filter((x) => x !== g) : [...cur, g]))}
                className={`rounded-full border px-3 py-1 text-xs ${
                  groups.includes(g) ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"
                }`}
              >
                {g}
              </button>
            ))}
          </div>

          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" maxLength={200}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm" />

          {mode === "paste" ? (
            <>
              <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Document text" rows={8} />
              <span className="text-xs text-muted-foreground">{text.length.toLocaleString()} / 20,000 characters</span>
            </>
          ) : (
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                choose(e.dataTransfer.files[0] ?? null);
              }}
              onClick={() => input.current?.click()}
              className="cursor-pointer rounded-lg border border-dashed p-8 text-center text-sm hover:bg-muted/40"
            >
              <input ref={input} type="file" hidden accept=".pdf,.docx,.txt,.md,.markdown,text/plain,application/pdf"
                onChange={(e) => choose(e.target.files?.[0] ?? null)} />
              {file ? (
                <span>{file.name} · {(file.size / 1000).toFixed(0)} kB</span>
              ) : (
                <span className="text-muted-foreground">Drop a PDF, Word (.docx), text or Markdown file here, or click to choose</span>
              )}
              <p className="mt-2 text-xs text-muted-foreground">
                Up to 10 MB and 200,000 characters of text. Scanned PDFs aren&apos;t supported, because there is no OCR.
              </p>
            </div>
          )}

          {groups.length === 0 && (
            <p className="text-xs text-muted-foreground">With no groups, nobody can read this document. That is a valid, fully locked state.</p>
          )}
          <div className="flex justify-end">
            <Button onClick={submit} disabled={busy || !tenant || !ready}>{busy ? "Indexing…" : "Upload"}</Button>
          </div>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {result && (
        <Card>
          <CardContent className="space-y-1 pt-6 text-sm">
            <div>
              <span className="font-mono">{result.id}</span> · {result.ready ? "live and searchable" : "waiting for ingestion…"}
            </div>
            <Link href={`/documents/${result.id}?tenant=${tenant}`} className="text-muted-foreground underline underline-offset-4">
              Open document
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

