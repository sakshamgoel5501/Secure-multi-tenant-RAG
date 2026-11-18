"use client";

import { useEffect, useState } from "react";
import { usePersona } from "@/components/persona-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import type { AskResult } from "@/lib/types";

const EXAMPLES = [
  "What is the team size for project amber-falcon-0?",
  "Which project is tracked by ticket TKT-1001?",
  "What is the annual budget for project amber-falcon-0?",
];

function AnswerText({ text }: { text: string }) {
  return (
    <p className="leading-relaxed">
      {text.split(/(\[S\d+\])/g).map((part, i) =>
        /^\[S\d+\]$/.test(part) ? (
          <span key={i} className="mx-0.5 rounded bg-muted px-1 text-xs font-medium text-muted-foreground">
            {part.slice(1, -1)}
          </span>
        ) : (
          part
        ),
      )}
    </p>
  );
}

const DETAIL_STAGES = ["embed", "dense", "lexical", "fuse", "state", "acl", "rerank"];

function Timing({ timing }: { timing: Record<string, number> }) {
  const total = timing.total ?? 0;
  const retrieve = timing.retrieve ?? 0;
  const generate = timing.generate ?? 0;
  const other = Math.max(0, total - retrieve - generate);
  const pct = (v: number) => (total > 0 ? `${(v / total) * 100}%` : "0%");
  const details = DETAIL_STAGES.filter((k) => k in timing);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">
          Where the time went <span className="text-muted-foreground">· {total.toFixed(0)} ms</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex h-2 overflow-hidden rounded-full bg-muted">
          <div className="bg-foreground/80" style={{ width: pct(retrieve) }} title="retrieval" />
          <div className="bg-foreground/40" style={{ width: pct(generate) }} title="generation" />
          <div className="bg-foreground/15" style={{ width: pct(other) }} title="other" />
        </div>
        <div className="flex gap-4 text-xs text-muted-foreground">
          <span>■ retrieval {retrieve.toFixed(0)} ms</span>
          <span>■ generation {generate.toFixed(0)} ms</span>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {details.map((k) => (
            <span key={k}>
              {k} {timing[k].toFixed(1)} ms
            </span>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Dense and lexical search run in parallel, so retrieval sub-stages overlap and don&apos;t add up.
        </p>
      </CardContent>
    </Card>
  );
}

export default function AskPage() {
  const { persona } = usePersona();
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setResult(null);
    setError(null);
  }, [persona?.id]);

  async function submit(q: string = question) {
    if (!q.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const body = await r.json();
      if (!r.ok) setError(body.error ?? `Request failed (${r.status})`);
      else setResult(body as AskResult);
    } catch {
      setError("Could not reach the frontend server.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Ask</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Answers come only from documents{" "}
          <span className="font-medium text-foreground">{persona?.label ?? "…"}</span> may read, with
          citations you can check against the source text.
        </p>
      </header>

      <div className="space-y-3">
        <Textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
          placeholder="Ask a question about the documents…"
          rows={3}
        />
        <div className="flex items-center justify-between">
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => {
                  setQuestion(ex);
                  submit(ex);
                }}
                className="rounded-full border px-3 py-1 text-xs text-muted-foreground hover:bg-muted/60"
              >
                {ex}
              </button>
            ))}
          </div>
          <Button onClick={() => submit()} disabled={loading || !question.trim()}>
            {loading ? "Thinking…" : "Ask"}
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="pt-6 text-sm">
            <span className="font-medium">Request failed.</span> {error}
          </CardContent>
        </Card>
      )}

      {result && (
        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-4 pt-6">
              <AnswerText text={result.data.answer} />
              <div className="flex flex-wrap gap-2">
                <Badge variant={result.data.grounded ? "default" : "secondary"}>
                  {result.data.grounded ? "grounded" : "not grounded"}
                </Badge>
                {result.data.degraded.map((d) => (
                  <Badge key={d} variant="outline">
                    degraded: {d}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>

          {result.data.citations.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-sm font-medium">Sources</h2>
              {result.data.citations.map((c) => {
                const passage = result.passages.find((p) => p.chunk_id === c.chunk_id);
                return (
                  <Card key={c.chunk_id}>
                    <CardContent className="space-y-2 pt-6">
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>
                          <span className="mr-2 rounded bg-muted px-1 font-medium">{c.marker}</span>
                          {c.title}
                        </span>
                        <span className="font-mono">
                          {c.document_id} v{c.version} · chars {c.start_offset}–{c.end_offset}
                        </span>
                      </div>
                      {passage && <p className="text-sm leading-relaxed">{passage.text}</p>}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}

          <Timing timing={result.timing} />
        </div>
      )}
    </div>
  );
}


